"""Operator endpoints are separate, authenticated, CSRF protected, and local only."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlmodel import Session
from test_weekly_ingestion import write_weekly

from app.main import app as public_app
from app.models import DatasetState, IngestionRun
from app.operator.app import create_operator_app


def test_operator_requires_authorization_and_trusted_origin(tmp_path):
    app = create_operator_app(secret="s" * 40, storage=tmp_path)
    with TestClient(app, base_url="http://localhost:8765") as client:
        assert client.get("/ops/health").status_code == 401
        assert client.post("/ops/login", json={"secret": "s" * 40}).status_code == 403
        assert (
            client.post(
                "/ops/login",
                headers={"Origin": "https://attacker.example"},
                json={"secret": "s" * 40},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/ops/login", headers={"Origin": "http://localhost:8765"}, json={"secret": "bad"}
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/ops/login", headers={"Origin": "http://localhost:8765"}, json={"secret": "s" * 40}
            ).status_code
            == 200
        )
        assert (
            client.post("/ops/batches", headers={"Origin": "http://localhost:8765"}).status_code
            == 403
        )
        assert client.get("/ops/session", headers={"Host": "attacker.example"}).status_code == 400


def authenticated(client):
    origin = {"Origin": "http://localhost:8765"}
    assert client.post("/ops/login", headers=origin, json={"secret": "s" * 40}).status_code == 200
    return {**origin, "X-CSRF-Token": client.get("/ops/session").json()["csrf"]}


def test_student_api_has_no_operator_routes():
    assert not any(getattr(route, "path", "").startswith("/ops") for route in public_app.routes)


@pytest.mark.postgres
def test_operator_preview_stage_confirm_publish_and_history(postgres_engine, tmp_path):
    source = tmp_path / "source"
    write_weekly(source)
    app = create_operator_app(engine=postgres_engine, secret="s" * 40, storage=tmp_path / "uploads")
    with TestClient(app, base_url="http://localhost:8765") as client:
        headers = authenticated(client)
        key = client.post("/ops/batches", headers=headers).json()["batch_id"]
        for path in source.iterdir():
            assert (
                client.put(
                    f"/ops/batches/{key}/files/{path.name}",
                    headers=headers,
                    content=path.read_bytes(),
                ).status_code
                == 200
            )
        preview = client.post(f"/ops/batches/{key}/preview", headers=headers)
        assert preview.status_code == 200, preview.text
        assert preview.json()["comparison"]["baseline_dataset_id"] is None
        with Session(postgres_engine) as session:
            assert session.scalar(select(func.count()).select_from(IngestionRun)) == 0
        staged = client.post(f"/ops/batches/{key}/stage", headers=headers, json={})
        assert staged.status_code == 200, staged.text
        dataset = staged.json()["dataset_id"]
        with Session(postgres_engine) as session:
            assert session.get_one(DatasetState, 1).active_dataset_id is None
        assert (
            client.post(
                f"/ops/batches/{key}/publish",
                headers=headers,
                json={"confirm_dataset_id": "wrong", "baseline_dataset_id": None},
            ).status_code
            == 409
        )
        changed = client.post(
            f"/ops/batches/{key}/publish",
            headers=headers,
            json={"confirm_dataset_id": dataset, "baseline_dataset_id": "different"},
        )
        assert changed.status_code == 409
        published = client.post(
            f"/ops/batches/{key}/publish",
            headers=headers,
            json={"confirm_dataset_id": dataset, "baseline_dataset_id": None},
        )
        assert published.status_code == 200, published.text
        health = client.get("/ops/health").json()
        assert health["active"]["dataset_id"] == dataset
        assert health["active"]["source_format"] == "weekly"
        assert len(health["active"]["days"]) == 7
        assert health["history"][0]["dataset_id"] == dataset
        assert "Synthetic booking" not in json.dumps(health)
        assert (
            client.put(
                f"/ops/batches/{key}/files/manifest.json", headers=headers, content=b"{}"
            ).status_code
            == 409
        )
        assert client.delete(f"/ops/batches/{key}", headers=headers).status_code == 200
        assert not list((tmp_path / "uploads").glob("ops-*"))


def test_operator_upload_boundaries_and_session_revocation(tmp_path):
    app = create_operator_app(secret="s" * 40, storage=tmp_path)
    with TestClient(app, base_url="http://localhost:8765") as client:
        headers = authenticated(client)
        key = client.post("/ops/batches", headers=headers).json()["batch_id"]
        for name in ["secret.txt", "manifest.json.exe"]:
            assert (
                client.put(
                    f"/ops/batches/{key}/files/{name}", headers=headers, content=b"no"
                ).status_code
                == 400
            )
        assert (
            client.put(
                f"/ops/batches/{key}/files/manifest.json", headers=headers, content=b"\x00"
            ).status_code
            == 400
        )
        assert (
            client.put(
                f"/ops/batches/{key}/files/manifest.json",
                headers=headers,
                content=b"x" * (1024 * 1024 + 1),
            ).status_code
            == 413
        )
        assert client.post("/ops/logout", headers=headers).status_code == 200
        assert client.get("/ops/session").status_code == 401


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/ops/session"),
        ("GET", "/ops/health"),
        ("POST", "/ops/batches"),
        ("PUT", "/ops/batches/unknown/files/export.html"),
        ("POST", "/ops/batches/unknown/preview"),
        ("POST", "/ops/batches/unknown/stage"),
        ("POST", "/ops/batches/unknown/publish"),
        ("DELETE", "/ops/batches/unknown"),
    ],
)
def test_every_privileged_route_rejects_anonymous_requests(tmp_path, method, path):
    app = create_operator_app(secret="s" * 40, storage=tmp_path)
    with TestClient(app, base_url="http://localhost:8765") as client:
        assert (
            client.request(method, path, headers={"Origin": "http://localhost:8765"}).status_code
            == 401
        )


def test_upload_storage_is_bounded_and_not_public(tmp_path):
    app = create_operator_app(secret="s" * 40, storage=tmp_path)
    with TestClient(app, base_url="http://localhost:8765") as client:
        headers = authenticated(client)
        for _ in range(5):
            assert client.post("/ops/batches", headers=headers).status_code == 200
        assert client.post("/ops/batches", headers=headers).status_code == 429
        assert client.get("/data/operator/").status_code == 404
        assert client.get("/ops/session").headers["cache-control"] == "no-store"
