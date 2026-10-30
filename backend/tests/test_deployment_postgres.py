import pytest
from sqlalchemy import text

from app import db

pytestmark = pytest.mark.postgres


def test_transaction_pooler_uses_local_settings_and_readonly_snapshot(postgres_engine, monkeypatch):
    monkeypatch.setenv("DATABASE_POOL_MODE", "transaction")
    monkeypatch.setenv("DATABASE_URL", postgres_engine.url.render_as_string(hide_password=False))
    engine = db.create_db_engine()
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    try:
        for _ in range(2):
            generator = db.get_read_session()
            session = next(generator)
            assert session.scalar(text("SHOW timezone")) == "UTC"
            assert session.scalar(text("SHOW statement_timeout")) == "3s"
            assert session.scalar(text("SHOW transaction_isolation")) == "repeatable read"
            assert session.scalar(text("SHOW transaction_read_only")) == "on"
            generator.close()
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            assert conn.scalar(text("SHOW statement_timeout")) == "0"
    finally:
        engine.dispose()


def test_synthetic_staging_and_sessions_survive_worker_replacement(
    postgres_engine, tmp_path, monkeypatch
):
    from datetime import UTC, date, datetime
    from uuid import UUID

    from fastapi.testclient import TestClient
    from test_hosting import FORWARDED, ORIGIN
    from test_student_auth_unit import PASSWORD, beta_config

    from app.hosting import create_vercel_app
    from app.ingest.local import IngestionError
    from app.ingest.pipeline import publish_dataset
    from app.main import utc_now
    from app.student_auth.service import StudentAuth, activate_policy
    from staging import generate, stage

    now = datetime(2026, 10, 30, 12, tzinfo=UTC)
    directory = tmp_path / "synthetic"
    generate(directory, date(2026, 10, 30), datetime(2026, 10, 29, 12, tzinfo=UTC))
    candidate = stage(postgres_engine, directory)
    assert candidate["status"] == "staged"
    dataset_id = UUID(candidate["dataset_id"])
    with postgres_engine.connect() as conn:
        assert conn.scalar(text("SELECT active_dataset_id FROM utscvacant.dataset_state")) is None
    publish_dataset(postgres_engine, dataset_id)
    with pytest.raises(IngestionError, match="staging_requires_empty_schedule"):
        stage(postgres_engine, directory)

    config = beta_config(origin=ORIGIN)
    activate_policy(postgres_engine, config)
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setattr(db, "get_engine", lambda: postgres_engine)

    def application():
        app = create_vercel_app()
        app.state.student_auth = StudentAuth(config, postgres_engine, clock=lambda: now)
        app.dependency_overrides[utc_now] = lambda: now
        return app

    headers = FORWARDED | {"Origin": ORIGIN, "X-Student-Request": "1"}
    with TestClient(application(), base_url=ORIGIN, headers=headers) as first:
        assert first.get("/api/v1/status").status_code == 401
        assert first.post("/auth/beta", json={"passcode": PASSWORD}).status_code == 200
        cookies = dict(first.cookies)
        status = first.get("/api/v1/status").json()
        assert status["dataset_id"] == str(dataset_id)
    with TestClient(application(), base_url=ORIGIN, headers=headers, cookies=cookies) as second:
        assert second.get("/auth/session").json()["authenticated"]
        assert second.get("/api/v1/status").json()["dataset_id"] == str(dataset_id)
        available = second.get(
            "/api/v1/availability", params={"start": now.isoformat(), "duration_minutes": 30}
        )
        assert available.status_code == 200
        assert len(available.json()["data"]) == 2
        csrf = second.get("/auth/session").json()["csrf"]
        assert (
            second.post("/auth/logout", json={}, headers={"X-CSRF-Token": csrf}).status_code == 200
        )
        assert second.get("/api/v1/status").status_code == 401

    import httpx

    from deployment_smoke import run_smoke

    with TestClient(application(), base_url=ORIGIN, headers=FORWARDED) as backend:

        def request(request):
            if request.url.path == "/":
                return httpx.Response(
                    200,
                    text="Intervella",
                    headers={"content-security-policy": "frame-ancestors 'none'"},
                )
            return backend.request(
                request.method,
                str(request.url),
                headers=dict(request.headers),
                content=request.content,
            )

        with httpx.Client(base_url=ORIGIN, transport=httpx.MockTransport(request)) as client:
            run_smoke(client, PASSWORD)


def test_deployment_grants_keep_runtime_roles_separate(postgres_engine):
    import re
    from pathlib import Path
    from uuid import uuid4

    from sqlalchemy.exc import DBAPIError

    root = Path(__file__).resolve().parents[2]
    names = [
        "intervella_migrator",
        "intervella_reader",
        "intervella_student_auth",
        "intervella_ingestor",
        "intervella_auth_admin",
        "anon",
        "authenticated",
        "service_role",
    ]
    prefix = "iv_test_" + uuid4().hex[:10] + "_"
    roles = {name: prefix + str(index) for index, name in enumerate(names)}

    def script(name):
        value = (root / "deploy" / name).read_text()
        for old, new in roles.items():
            value = re.sub(r"\b" + old + r"\b", new, value)
        value = value.replace(
            "ON DATABASE postgres", 'ON DATABASE "' + postgres_engine.url.database + '"'
        )
        return value.replace("BEGIN;", "").replace("COMMIT;", "")

    with postgres_engine.connect() as conn:
        transaction = conn.begin()
        try:
            for name in ["anon", "authenticated", "service_role"]:
                conn.exec_driver_sql('CREATE ROLE "' + roles[name] + '" NOLOGIN')
            conn.exec_driver_sql(script("roles.sql"))
            conn.exec_driver_sql(script("grants.sql"))
            reader = roles["intervella_reader"]
            auth = roles["intervella_student_auth"]
            for role in [reader, auth]:
                assert conn.scalar(
                    text(
                        "SELECT NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole "
                        "FROM pg_roles WHERE rolname=:r"
                    ),
                    {"r": role},
                )
            conn.exec_driver_sql('SET LOCAL ROLE "' + reader + '"')
            conn.exec_driver_sql("SELECT * FROM utscvacant.datasets")
            for query in [
                "SELECT * FROM student_auth.session",
                "UPDATE utscvacant.dataset_state SET id=id",
            ]:
                with pytest.raises(DBAPIError), conn.begin_nested():
                    conn.exec_driver_sql(query)
            conn.exec_driver_sql("RESET ROLE")
            conn.exec_driver_sql('SET LOCAL ROLE "' + auth + '"')
            conn.exec_driver_sql("SELECT * FROM student_auth.session")
            conn.exec_driver_sql("SELECT * FROM student_auth.control FOR SHARE")
            for query in [
                "SELECT * FROM utscvacant.rooms",
                "UPDATE student_auth.control SET policy=policy",
                "CREATE TABLE student_auth.forbidden(id int)",
            ]:
                with pytest.raises(DBAPIError), conn.begin_nested():
                    conn.exec_driver_sql(query)
        finally:
            transaction.rollback()
