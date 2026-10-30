from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest
from fastapi.testclient import TestClient
from schedule_helpers import NOW, make_schedule
from sqlalchemy import func, select
from starlette.requests import Request
from test_student_auth_unit import PASSWORD, beta_config, university_config
from test_student_auth_unit import signed_provider as signed_provider

from app import db
from app.errors import APIError
from app.main import create_app, utc_now
from app.student_auth.service import StudentAuth, activate_policy, password_hash
from app.student_auth.tables import sessions

pytestmark = pytest.mark.postgres
ORIGIN = "https://student.test"
HEADERS = {"Origin": ORIGIN, "X-Student-Request": "1", "Content-Type": "application/json"}
PATHS = [
    "/api/v1/availability",
    "/api/v1/room-search",
    "/api/v1/buildings",
    "/api/v1/rooms/1",
    "/api/v1/rooms/1/schedule",
    "/api/v1/buildings/SYN/schedule",
    "/api/v1/status",
    "/health/ready",
    "/openapi.json",
    "/docs",
    "/api//v1/rooms/1",
    "/api/v1/rooms/%31/",
    "/api/v1/rooms/0",
    "/api/v1/rooms/1%2fschedule",
    "/ops/health",
]


@pytest.fixture
def auth_setup(postgres_engine, monkeypatch):
    config = beta_config(beta_ends_at=NOW + timedelta(days=7))
    activate_policy(postgres_engine, config)
    monkeypatch.setattr(db, "get_engine", lambda: postgres_engine)
    clock = [NOW]
    app = create_app()
    app.state.student_auth = StudentAuth(config, postgres_engine, clock=lambda: clock[0])
    app.dependency_overrides[utc_now] = lambda: NOW
    with TestClient(app, base_url=ORIGIN) as client:
        yield client, app, config, clock


def signin(client):
    response = client.post("/auth/beta", json={"passcode": PASSWORD}, headers=HEADERS)
    assert response.status_code == 200, response.text
    return client.get("/auth/session").json()["csrf"]


@pytest.mark.parametrize("path", PATHS)
def test_all_data_and_alternate_routes_require_session(auth_setup, path):
    client, _, _, _ = auth_setup
    response = client.get(path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"
    assert response.headers["cache-control"] == "private, no-store"
    assert "dataset_id" not in response.text


def test_beta_login_cookie_contract_and_schedule_access(auth_setup, postgres_engine):
    client, _, config, _ = auth_setup
    make_schedule(postgres_engine)
    response = client.post("/auth/beta", json={"passcode": PASSWORD}, headers=HEADERS)
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "__Host-intervella_student=" in cookie
    assert all(value in cookie for value in ["HttpOnly", "Secure", "SameSite=lax", "Path=/"])
    token = client.cookies.get(config.cookie)
    with postgres_engine.connect() as conn:
        row = conn.execute(select(sessions)).mappings().one()
    assert row["id"] != token and token not in str(row) and PASSWORD not in str(row)
    csrf = client.get("/auth/session").json()["csrf"]
    assert csrf == row["csrf"]
    buildings = client.get("/api/v1/buildings").json()["data"]
    code = buildings[0]["code"]
    paths = [
        "/api/v1/buildings",
        "/api/v1/status",
        "/api/v1/rooms/1",
        "/api/v1/availability?start=" + NOW.isoformat().replace("+", "%2B"),
        "/api/v1/room-search?start=" + NOW.isoformat().replace("+", "%2B"),
        "/api/v1/rooms/1/schedule?date=2026-10-14",
        f"/api/v1/buildings/{code}/schedule?date=2026-10-14",
        "/health/ready",
    ]
    for path in paths:
        assert client.get(path).status_code == 200, path


def test_invalid_missing_passcodes_and_origin_do_not_leak(auth_setup, caplog):
    client, _, _, _ = auth_setup
    for body in [{}, {"passcode": ""}, {"passcode": 5}]:
        assert client.post("/auth/beta", json=body, headers=HEADERS).status_code == 422
    for headers in [
        {},
        HEADERS | {"Origin": "https://evil.test"},
        HEADERS | {"X-Student-Request": ""},
    ]:
        assert (
            client.post("/auth/beta", json={"passcode": PASSWORD}, headers=headers).status_code
            == 403
        )
    response = client.post(
        "/auth/beta", json={"passcode": "wrong-synthetic-private-value"}, headers=HEADERS
    )
    assert response.status_code == 401
    assert "wrong-synthetic-private-value" not in response.text + caplog.text
    assert client.post("/auth/beta", content=b"x" * 4097, headers=HEADERS).status_code == 413


def test_logout_csrf_and_reuse_of_stolen_cookie(auth_setup):
    client, _, config, _ = auth_setup
    csrf = signin(client)
    token = client.cookies.get(config.cookie)
    assert client.post("/auth/logout", json={}, headers=HEADERS).status_code == 403
    assert client.get("/auth/session").json()["authenticated"]
    assert (
        client.post("/auth/renew", json={}, headers=HEADERS | {"X-CSRF-Token": "wrong"}).status_code
        == 403
    )
    assert (
        client.post("/auth/logout", json={}, headers=HEADERS | {"X-CSRF-Token": csrf}).status_code
        == 200
    )
    assert not client.get("/auth/session").json()["authenticated"]
    assert (
        client.get("/api/v1/status", headers={"Cookie": f"{config.cookie}={token}"}).status_code
        == 401
    )


def test_fixed_beta_deadline_and_session_expiration(auth_setup):
    client, _, _, clock = auth_setup
    signin(client)
    clock[0] = NOW + timedelta(days=7, seconds=1)
    assert client.get("/api/v1/status").status_code == 401
    assert not client.get("/auth/session").json()["authenticated"]
    assert (
        client.post("/auth/beta", json={"passcode": PASSWORD}, headers=HEADERS).status_code == 403
    )
    assert client.post("/auth/logout", json={}, headers=HEADERS).status_code == 200


def test_replicas_share_limits_and_revocation(auth_setup, postgres_engine):
    client, _, config, _ = auth_setup
    for _ in range(10):
        assert (
            client.post("/auth/beta", json={"passcode": "wrong"}, headers=HEADERS).status_code
            == 401
        )
    second = create_app()
    second.state.student_auth = StudentAuth(config, postgres_engine, clock=lambda: NOW)
    with TestClient(second, base_url=ORIGIN) as replica:
        assert (
            replica.post("/auth/beta", json={"passcode": PASSWORD}, headers=HEADERS).status_code
            == 429
        )


def test_mode_switch_and_return_to_beta_never_revive_old_sessions(auth_setup, postgres_engine):
    client, _, config, _ = auth_setup
    signin(client)
    token = client.cookies.get(config.cookie)
    activate_policy(postgres_engine, university_config())
    assert client.get("/api/v1/status").status_code == 503
    activate_policy(postgres_engine, config)
    assert (
        client.get("/api/v1/status", headers={"Cookie": f"{config.cookie}={token}"}).status_code
        == 401
    )
    signin(client)
    rotated = replace(config, password_hash=password_hash("rotated-synthetic-beta-passcode"))
    activate_policy(postgres_engine, rotated)
    assert client.get("/api/v1/status").status_code == 503


def test_atomic_limits_across_concurrent_connections(auth_setup, postgres_engine):
    _, app, _, _ = auth_setup
    request = Request(
        {
            "type": "http",
            "scheme": "https",
            "server": ("student.test", 443),
            "path": "/auth/beta",
            "headers": [],
            "client": ("192.0.2.1", 1234),
        }
    )

    def attempt(_):
        try:
            app.state.student_auth.limit(request, "concurrent")
            return 200
        except APIError as error:
            return error.status_code

    with ThreadPoolExecutor(max_workers=8) as workers:
        statuses = list(workers.map(attempt, range(20)))
    assert statuses.count(200) == 10 and statuses.count(429) == 10


def test_activation_waits_for_inflight_session_creation(auth_setup, postgres_engine, monkeypatch):
    _, app, config, _ = auth_setup
    auth = app.state.student_auth
    acquired, release = Event(), Event()
    original = auth.policy

    def guarded(conn, lock=False):
        original(conn, lock)
        acquired.set()
        assert release.wait(5)

    monkeypatch.setattr(auth, "policy", guarded)
    request = Request(
        {
            "type": "http",
            "scheme": "https",
            "server": ("student.test", 443),
            "path": "/auth/beta",
            "headers": [],
            "client": ("192.0.2.1", 1234),
        }
    )
    next_config = replace(config, epoch="synthetic-new-epoch-for-revocation-0002")
    with ThreadPoolExecutor(max_workers=2) as workers:
        creation = workers.submit(auth.create, request)
        assert acquired.wait(5)
        activation = workers.submit(activate_policy, postgres_engine, next_config)
        try:
            with pytest.raises(FutureTimeout):
                activation.result(timeout=0.1)
        finally:
            release.set()
        creation.result(timeout=5)
        activation.result(timeout=5)
    with postgres_engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(sessions)) == 0


def test_university_code_exchange_renewal_and_logout(postgres_engine, signed_provider):
    import json

    import httpx
    import jwt
    from sqlalchemy import update

    provider, key, claims, token, user, calls = signed_provider
    config = provider.config
    activate_policy(postgres_engine, config)
    provider.client.close()
    refreshes, logouts = [], []
    refresh_token = "synthetic-refresh-token-private"
    next_token = jwt.encode(
        claims | {"exp": claims["exp"] + 600},
        key,
        algorithm="RS256",
        headers={"kid": "synthetic-key"},
    )

    def respond(request):
        calls.append(request)
        if request.url.path.endswith("/user"):
            return httpx.Response(200, json=user)
        if request.url.path.endswith("/otp"):
            assert json.loads(request.content)["email"] == "friend@university.test"
            return httpx.Response(200, json={})
        if request.url.path.endswith("/verify"):
            assert json.loads(request.content)["type"] == "email"
            return httpx.Response(200, json={"access_token": token, "refresh_token": refresh_token})
        if request.url.path.endswith("/token"):
            refreshes.append(request)
            assert json.loads(request.content)["refresh_token"] == refresh_token
            return httpx.Response(
                200, json={"access_token": next_token, "refresh_token": "rotated-synthetic-refresh"}
            )
        if request.url.path.endswith("/logout"):
            logouts.append(request)
            return httpx.Response(204)
        raise AssertionError(request.url.path)

    provider.client = httpx.Client(transport=httpx.MockTransport(respond))
    app = create_app()
    app.state.student_auth = StudentAuth(config, postgres_engine, provider=provider)
    with TestClient(app, base_url=ORIGIN) as client:
        assert (
            client.post("/auth/beta", json={"passcode": PASSWORD}, headers=HEADERS).status_code
            == 404
        )
        assert (
            client.post(
                "/auth/university/code",
                json={"email": "friend@university.test.evil.test"},
                headers=HEADERS,
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/auth/university/code", json={"email": "friend@university.test"}, headers=HEADERS
            ).status_code
            == 200
        )
        response = client.post(
            "/auth/university/verify",
            json={"email": "friend@university.test", "code": "123456"},
            headers=HEADERS,
        )
        assert response.status_code == 200
        assert token not in response.text and refresh_token not in response.text
        state = client.get("/auth/session").json()
        assert state["authenticated"]
        csrf = state["csrf"]
        with postgres_engine.begin() as conn:
            conn.execute(
                update(sessions).values(access_expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
        assert client.get("/api/v1/status").status_code == 401
        assert client.get("/auth/session").json()["needs_renewal"]
        result = client.post("/auth/renew", json={}, headers=HEADERS | {"X-CSRF-Token": csrf})
        assert result.status_code == 200 and result.json()["authenticated"]
        assert len(refreshes) == 1
        assert (
            client.post(
                "/auth/renew", json={}, headers=HEADERS | {"X-CSRF-Token": csrf}
            ).status_code
            == 200
        )
        assert len(refreshes) == 1
        with postgres_engine.connect() as conn:
            row = conn.execute(select(sessions)).mappings().one()
            assert (
                refresh_token not in row["provider_tokens"]
                and next_token not in row["provider_tokens"]
            )
        assert (
            client.post(
                "/auth/logout", json={}, headers=HEADERS | {"X-CSRF-Token": csrf}
            ).status_code
            == 200
        )
        assert len(logouts) == 1
        assert client.get("/api/v1/status").status_code == 401


def test_documented_auth_role_has_no_schedule_or_policy_write_access(connection):
    from uuid import uuid4

    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    role = "utscvacant_test_auth_" + uuid4().hex
    connection.execute(text(f'CREATE ROLE "{role}" NOLOGIN'))
    connection.execute(text(f'GRANT USAGE ON SCHEMA student_auth TO "{role}"'))
    connection.execute(
        text(
            "GRANT SELECT,INSERT,UPDATE,DELETE ON student_auth.session,student_auth.attempt "
            f'TO "{role}"'
        )
    )
    connection.execute(text(f'GRANT SELECT ON student_auth.control TO "{role}"'))
    connection.execute(text(f'GRANT UPDATE(id) ON student_auth.control TO "{role}"'))
    config = beta_config()
    connection.execute(
        text("UPDATE student_auth.control SET policy=:policy"), {"policy": config.fingerprint}
    )
    connection.execute(text(f'SET LOCAL ROLE "{role}"'))
    assert connection.scalar(text("SELECT id FROM student_auth.control")) == 1
    StudentAuth(config).policy(connection, lock=True)
    connection.execute(
        sessions.insert().values(
            id="a" * 64,
            policy="b" * 64,
            csrf="c" * 64,
            expires_at=NOW + timedelta(days=1),
            subject="synthetic",
        )
    )
    for statement in [
        "SELECT * FROM utscvacant.rooms",
        "UPDATE student_auth.control SET policy='forbidden'",
        "CREATE TABLE student_auth.forbidden (id integer)",
    ]:
        with pytest.raises(DBAPIError), connection.begin_nested():
            connection.execute(text(statement))


def test_admin_cli_checks_target_and_activates_only_disposable_auth_database(postgres_engine):
    import os
    import subprocess
    import sys
    from pathlib import Path

    from app.student_auth.tables import control

    config = beta_config()
    url = postgres_engine.url.render_as_string(hide_password=False)
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("STUDENT_")
    }
    environment.update(
        STUDENT_AUTH_MODE="beta",
        STUDENT_AUTH_ORIGIN=config.origin,
        STUDENT_AUTH_EPOCH=config.epoch,
        STUDENT_BETA_PASSWORD_HASH=config.password_hash,
        STUDENT_BETA_ENDS_AT=config.beta_ends_at.isoformat(),
        STUDENT_AUTH_DATABASE_URL=url,
        STUDENT_AUTH_ADMIN_DATABASE_URL=postgres_engine.url.set(
            database="postgres"
        ).render_as_string(hide_password=False),
    )
    arguments = [sys.executable, "-m", "app.student_auth", "activate"]
    directory = Path(__file__).resolve().parents[1]
    denied = subprocess.run(
        arguments, cwd=directory, env=environment, capture_output=True, text=True, timeout=20
    )
    assert denied.returncode != 0 and "same auth database" in denied.stderr
    with postgres_engine.connect() as conn:
        assert conn.scalar(select(control.c.policy)) == ""
    environment["STUDENT_AUTH_ADMIN_DATABASE_URL"] = url
    result = subprocess.run(
        arguments, cwd=directory, env=environment, capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stderr
    assert config.password_hash not in result.stdout + result.stderr
    with postgres_engine.connect() as conn:
        assert conn.scalar(select(control.c.policy)) == config.fingerprint
