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

pytestmark = pytest.mark.postgres


def test_real_http_availability(postgres_engine):
    now = datetime.now(UTC)
    make_schedule(
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
    environment = {
        **os.environ,
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
            "--log-level",
            "warning",
        ],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=2) as client:
            deadline = monotonic() + 10
            while True:
                if process.poll() is not None:
                    pytest.fail(f"uvicorn exited: {process.communicate()[1].decode()}")
                try:
                    if client.get("/health/live").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                assert monotonic() < deadline, "uvicorn did not become live"
                sleep(0.05)
            response = client.get("/api/v1/availability", params={"start": now.isoformat()})
            assert response.status_code == 200
            body = response.json()
            assert [room["room_id"] for room in body["data"]] == [1, 2, 6]
            assert datetime.fromisoformat(body["data"][0]["next_booking"]) == now + timedelta(
                hours=1
            )
            assert client.get("/health/ready").status_code == 200
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        if process.stderr:
            process.stderr.close()
