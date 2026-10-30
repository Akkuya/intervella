"""Exercise the actual uvicorn HTTP boundary against a dedicated test database."""

import os
import socket
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from time import monotonic, sleep

import httpx
import pytest
from schedule_helpers import make_schedule
from test_student_auth_unit import PASSWORD, beta_config

from app.student_auth.service import activate_policy

pytestmark = pytest.mark.postgres


def test_real_http_availability(postgres_engine):
    now = datetime.now(UTC)
    dataset_id = make_schedule(
        postgres_engine,
        fetched_at=now,
        coverage={
            room: (now - timedelta(days=1), now + timedelta(days=1), "complete")
            for room in (1, 2, 6)
        },
        meetings=[(1, now + timedelta(hours=1), now + timedelta(hours=2), "scheduled")],
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    config = beta_config(origin=f"http://127.0.0.1:{port}")
    activate_policy(postgres_engine, config)
    environment = {
        **{
            key: value
            for key, value in os.environ.items()
            if not key.startswith("STUDENT_")
            and key
            not in {
                "TEST_DATABASE_URL",
                "INGESTION_DATABASE_URL",
                "MIGRATION_DATABASE_URL",
                "OPERATOR_SECRET",
            }
        },
        "STUDENT_AUTH_MODE": "beta",
        "STUDENT_AUTH_ORIGIN": config.origin,
        "STUDENT_AUTH_EPOCH": config.epoch,
        "STUDENT_BETA_PASSWORD_HASH": config.password_hash,
        "STUDENT_BETA_ENDS_AT": config.beta_ends_at.isoformat(),
        "STUDENT_AUTH_DATABASE_URL": postgres_engine.url.render_as_string(hide_password=False),
        "DATABASE_URL": postgres_engine.url.render_as_string(hide_password=False),
        "FRESHNESS_MAX_AGE_HOURS": "36",
        "MAX_AVAILABILITY_LIMIT": "100",
        "API_REQUEST_TIMEOUT_SECONDS": "15",
        "ALLOWED_ORIGINS": "",
    }
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=2) as client:
            deadline = monotonic() + 10
            while True:
                if process.poll() is not None:
                    pytest.fail(f"uvicorn exited: {process.communicate()[0].decode()}")
                try:
                    if client.get("/health/live").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                assert monotonic() < deadline, "uvicorn did not become live"
                sleep(0.05)
            assert client.get("/api/v1/status").status_code == 401
            login = client.post(
                "/auth/beta",
                json={"passcode": PASSWORD},
                headers={"Origin": config.origin, "X-Student-Request": "1"},
            )
            assert login.status_code == 200
            response = client.get(
                "/api/v1/availability",
                params={"start": now.isoformat(), "private_probe": "NEVER_LOG_QUERY"},
            )
            assert response.status_code == 200
            body = response.json()
            assert [room["room_id"] for room in body["data"]] == [1, 2, 6]
            assert datetime.fromisoformat(body["data"][0]["next_booking"]) == now + timedelta(
                hours=1
            )
            assert client.get("/health/ready").status_code == 200
            enhanced = client.get(
                "/api/v1/room-search",
                params={
                    "start": now.isoformat(),
                    "end": (now + timedelta(hours=1)).isoformat(),
                    "room_ids": [1, 2, 7],
                },
            )
            assert enhanced.status_code == 200
            search = enhanced.json()
            assert search["meta"]["dataset_id"] == str(dataset_id)
            assert [room["state"] for room in search["data"]] == [
                "available",
                "available",
                "inactive",
            ]
            assert datetime.fromisoformat(search["data"][0]["available_until"]) == now + timedelta(
                hours=1
            )
    finally:
        process.terminate()
        try:
            output, _ = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            output, _ = process.communicate(timeout=5)
    logs = output.decode(errors="replace")
    assert PASSWORD not in logs
    assert "NEVER_LOG_QUERY" not in logs
    assert "start=" not in logs
    assert f"request_id={response.headers['x-request-id']}" in logs
    assert "route=/api/v1/availability status=200" in logs
    assert f"dataset_id={dataset_id}" in logs
