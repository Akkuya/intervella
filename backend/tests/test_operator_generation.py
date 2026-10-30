import pytest
from fastapi.testclient import TestClient
from ingestion_helpers import write_bundle
from sqlalchemy import select
from sqlmodel import Session
from test_operator import authenticated
from test_weekly_ingestion import write_weekly

from app.ingest.local import load_directory
from app.models import DatasetState, Room
from app.operator.app import create_operator_app


def upload(client, headers, source):
    key = client.post("/ops/batches", headers=headers).json()["batch_id"]
    for path in sorted(source.glob("*.html")):
        assert (
            client.put(
                f"/ops/batches/{key}/files/{path.name}", headers=headers, content=path.read_bytes()
            ).status_code
            == 200
        )
    return key


def approve(client, headers, result, version=0):
    draft = result["draft"]
    response = client.put(
        "/ops/inventory-profile",
        headers=headers,
        json={
            "expected_version": version,
            "expected_rooms": sum(len(b["rooms"]) for b in draft["buildings"]),
            "expected_buildings": len(draft["buildings"]),
            "review_reason": "inventory-independent",
            "review_acknowledged": True,
            "source_formats": [draft["source_format"]],
            "window": draft["window"],
            "buildings": draft["buildings"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["profile"]


def prepare(client, headers, key, start):
    response = client.post(
        f"/ops/batches/{key}/analyze", headers=headers, json={"start_date": start}
    )
    assert response.status_code == 200, response.text
    result = response.json()
    profile = approve(client, headers, result)
    draft = result["draft"]
    if draft["source_format"] == "weekly":
        draft["inventory_review_reason"] = "inventory-independent"
    for item in draft.get("weeks", draft.get("snapshots", [])):
        item["fetched_at"] = "2026-10-14T11:00:00Z"
        item["capture_evidence"] = "Synthetic fixture capture record"
    review = {
        "analysis_hash": result["analysis_hash"],
        "profile_version": profile["version"],
        "manifest": draft,
        "review_reason": "inventory-independent",
        "review_acknowledged": True,
        "capture_acknowledged": True,
        "target_acknowledged": True,
    }
    return review


@pytest.mark.parametrize(
    "route,method",
    [
        ("/ops/inventory-profile", "GET"),
        ("/ops/inventory-profile", "PUT"),
        ("/ops/batches/no/analyze", "POST"),
        ("/ops/batches/no/manifest", "POST"),
        ("/ops/batches/no/discover", "POST"),
        ("/ops/batches/no/coverage-profile", "POST"),
        ("/ops/publications", "POST"),
    ],
)
def test_new_operator_routes_require_auth_and_csrf(tmp_path, route, method):
    with TestClient(
        create_operator_app(secret="s" * 40, storage=tmp_path), base_url="http://localhost:8765"
    ) as c:
        assert c.request(method, route, json={}).status_code == 401
        headers = authenticated(c)
        if method != "GET":
            assert (
                c.request(method, route, headers={"Origin": headers["Origin"]}, json={}).status_code
                == 403
            )


@pytest.mark.parametrize("kind", ["daily", "weekly"])
def test_generated_manifest_requires_profile_and_real_capture_confirmation_without_db(
    tmp_path, kind
):
    source = tmp_path / "source"
    if kind == "daily":
        write_bundle(source)
    else:
        write_weekly(source)
    start = "2026-10-14" if kind == "daily" else "2026-10-25"
    with TestClient(
        create_operator_app(secret="s" * 40, storage=tmp_path / "private"),
        base_url="http://localhost:8765",
    ) as c:
        h = authenticated(c)
        key = upload(c, h, source)
        review = prepare(c, h, key, start)
        review["target_acknowledged"] = False
        assert (
            c.post(f"/ops/batches/{key}/manifest", headers=h, json=review).json()["error"]["code"]
            == "target_confirmation_required"
        )
        review["target_acknowledged"] = True
        review["capture_acknowledged"] = False
        assert (
            c.post(f"/ops/batches/{key}/manifest", headers=h, json=review).json()["error"]["code"]
            == "capture_confirmation_required"
        )
        review["capture_acknowledged"] = True
        review["manifest"].get("weeks", review["manifest"].get("snapshots"))[0]["fetched_at"] = ""
        assert c.post(f"/ops/batches/{key}/manifest", headers=h, json=review).status_code == 400
        review["manifest"].get("weeks", review["manifest"].get("snapshots"))[0]["fetched_at"] = (
            "2026-10-14T11:00:00Z"
        )
        response = c.post(f"/ops/batches/{key}/manifest", headers=h, json=review)
        assert response.status_code == 200, response.text
        assert len(load_directory(tmp_path / "private" / f"ops-{key}").dates) == 7
        assert "Synthetic booking" not in response.text
        assert c.get("/ops/inventory-profile").json()["profile"]["version"] == 1
        assert c.get("/inventory/current.json").status_code == 404
        c.delete(f"/ops/batches/{key}", headers=h)
        assert c.get("/ops/inventory-profile").json()["profile"]["version"] == 1


def test_source_changes_and_profile_changes_invalidate_review(tmp_path):
    source = tmp_path / "source"
    write_weekly(source)
    with TestClient(
        create_operator_app(secret="s" * 40, storage=tmp_path / "private"),
        base_url="http://localhost:8765",
    ) as c:
        h = authenticated(c)
        key = upload(c, h, source)
        review = prepare(c, h, key, "2026-10-25")
        result = c.post(
            f"/ops/batches/{key}/analyze", headers=h, json={"start_date": "2026-10-25"}
        ).json()
        approve(c, h, result, 1)
        assert (
            c.post(f"/ops/batches/{key}/manifest", headers=h, json=review).json()["error"]["code"]
            == "profile_changed"
        )
        review["profile_version"] = 2
        path = next(source.glob("*.html"))
        c.put(f"/ops/batches/{key}/files/{path.name}", headers=h, content=path.read_bytes() + b"\n")
        assert (
            c.post(f"/ops/batches/{key}/manifest", headers=h, json=review).json()["error"]["code"]
            == "analysis_required"
        )
        assert c.post(f"/ops/batches/{key}/stage", headers=h, json={}).status_code == 409


@pytest.mark.postgres
@pytest.mark.parametrize("kind", ["daily", "weekly"])
def test_upload_generate_review_stage_and_explicit_atomic_publish(postgres_engine, tmp_path, kind):
    source = tmp_path / "source"
    if kind == "daily":
        write_bundle(source)
    else:
        write_weekly(source)
    start = "2026-10-14" if kind == "daily" else "2026-10-25"
    app = create_operator_app(engine=postgres_engine, secret="s" * 40, storage=tmp_path / "private")
    with TestClient(app, base_url="http://localhost:8765") as c:
        h = authenticated(c)
        key = upload(c, h, source)
        review = prepare(c, h, key, start)
        assert c.post(f"/ops/batches/{key}/manifest", headers=h, json=review).status_code == 200
        with Session(postgres_engine) as s:
            assert s.get_one(DatasetState, 1).active_dataset_id is None
        preview = c.post(f"/ops/batches/{key}/preview", headers=h)
        assert preview.status_code == 200, preview.text
        response = c.post(
            f"/ops/batches/{key}/stage",
            headers=h,
            json={"review_reason": "inventory-independent", "review_acknowledged": True},
        )
        assert response.status_code == 200, response.text
        candidate = response.json()["dataset_id"]
        with Session(postgres_engine) as s:
            assert s.get_one(DatasetState, 1).active_dataset_id is None
        published = c.post(
            f"/ops/batches/{key}/publish",
            headers=h,
            json={
                "confirm_dataset_id": candidate,
                "baseline_dataset_id": None,
                "review_reason": "inventory-independent",
                "review_acknowledged": True,
            },
        )
        assert published.status_code == 200, published.text
        with Session(postgres_engine) as s:
            ids = {r.room_number: r.id for r in s.scalars(select(Room)).all()}
        # A new source hash with exactly approved canonical mappings keeps stable DB IDs.
        c.delete(f"/ops/batches/{key}", headers=h)
        path = next(source.glob("*.html"))
        path.write_bytes(path.read_bytes() + b"\n")
        key = upload(c, h, source)
        result = c.post(f"/ops/batches/{key}/analyze", headers=h, json={"start_date": start}).json()
        assert not result["bootstrap_required"]
        review["analysis_hash"] = result["analysis_hash"]
        assert c.post(f"/ops/batches/{key}/manifest", headers=h, json=review).status_code == 200
        c.post(f"/ops/batches/{key}/preview", headers=h)
        again = c.post(f"/ops/batches/{key}/stage", headers=h, json={})
        assert again.status_code == 200, again.text
        with Session(postgres_engine) as s:
            assert {r.room_number: r.id for r in s.scalars(select(Room)).all()} == ids
            assert str(s.get_one(DatasetState, 1).active_dataset_id) == candidate


def test_generated_review_cannot_be_bypassed_by_previewing_changed_uploads(tmp_path):
    source = tmp_path / "source"
    write_weekly(source)
    with TestClient(
        create_operator_app(secret="s" * 40, storage=tmp_path / "private"),
        base_url="http://localhost:8765",
    ) as client:
        headers = authenticated(client)
        key = upload(client, headers, source)
        review = prepare(client, headers, key, "2026-10-25")
        assert (
            client.post(f"/ops/batches/{key}/manifest", headers=headers, json=review).status_code
            == 200
        )
        path = next(source.glob("*.html"))
        client.put(
            f"/ops/batches/{key}/files/{path.name}",
            headers=headers,
            content=path.read_bytes() + b" ",
        )
        # Validation must stop before trying to open a database or compare a stale review.
        response = client.post(f"/ops/batches/{key}/preview", headers=headers)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "manifest_review_required"


def test_upload_expiry_does_not_expire_approved_inventory(tmp_path):
    import os
    import time

    source = tmp_path / "source"
    write_weekly(source)
    with TestClient(
        create_operator_app(secret="s" * 40, storage=tmp_path / "private"),
        base_url="http://localhost:8765",
    ) as client:
        headers = authenticated(client)
        key = upload(client, headers, source)
        prepare(client, headers, key, "2026-10-25")
        old = time.time() - 3700
        os.utime(tmp_path / "private" / f"ops-{key}", (old, old))
        assert client.get("/ops/inventory-profile").json()["profile"]["version"] == 1
        assert not (tmp_path / "private" / f"ops-{key}").exists()


@pytest.mark.postgres
def test_profile_approval_cannot_race_generated_publication(postgres_engine, tmp_path, monkeypatch):
    from app.ingest.local import IngestionError
    from app.operator import app as operator_module
    from app.operator.profiles import ProfileApproval, ProfileStore, inventory_value

    source = tmp_path / "source"
    write_weekly(source)
    app = create_operator_app(engine=postgres_engine, secret="s" * 40, storage=tmp_path / "private")
    with TestClient(app, base_url="http://localhost:8765") as client:
        headers = authenticated(client)
        key = upload(client, headers, source)
        review = prepare(client, headers, key, "2026-10-25")
        assert (
            client.post(f"/ops/batches/{key}/manifest", headers=headers, json=review).status_code
            == 200
        )
        assert client.post(f"/ops/batches/{key}/preview", headers=headers).status_code == 200
        staged = client.post(f"/ops/batches/{key}/stage", headers=headers, json={}).json()[
            "dataset_id"
        ]
        store = ProfileStore(tmp_path / "private" / "inventory")
        profile = store.current()
        approval = ProfileApproval(
            **inventory_value(profile),
            expected_version=1,
            expected_rooms=2,
            expected_buildings=1,
            review_reason="concurrent-inventory",
            review_acknowledged=True,
        )
        publish = operator_module.publish_dataset
        approval_results = []

        def during_publication(*args, **kwargs):
            # Concurrent approvals cannot pass the publication lock, even on another descriptor.
            try:
                store.save(approval)
                approval_results.append("approved")
            except IngestionError as error:
                approval_results.append(error.code)
            return publish(*args, **kwargs)

        monkeypatch.setattr(operator_module, "publish_dataset", during_publication)
        response = client.post(
            f"/ops/batches/{key}/publish",
            headers=headers,
            json={"confirm_dataset_id": staged, "baseline_dataset_id": None},
        )
        assert response.status_code == 200, response.text
        assert approval_results == ["profile_busy"]
        assert store.current().version == 1
