import pytest
from fastapi.testclient import TestClient

from app.errors import APIError
from app.hosting import create_vercel_app
from app.student_auth.service import StudentAuth

ORIGIN = "https://student.test"
FORWARDED = {"x-forwarded-proto": "https", "x-vercel-forwarded-for": "192.0.2.2"}


@pytest.fixture
def hosted(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("DATABASE_POOL_MODE", "transaction")
    for key in ["DATABASE_URL", "STUDENT_AUTH_DATABASE_URL"]:
        monkeypatch.setenv(key, "postgresql://reader@pooler.test:6543/postgres?sslmode=require")
    monkeypatch.setenv("STUDENT_AUTH_MODE", "beta")
    monkeypatch.setenv("STUDENT_AUTH_ORIGIN", ORIGIN)
    monkeypatch.setenv("STUDENT_AUTH_EPOCH", "synthetic-epoch-for-tests-only-12345")
    monkeypatch.setenv("STUDENT_BETA_ENDS_AT", "2099-01-01T00:00:00Z")
    monkeypatch.setenv("STUDENT_BETA_PASSWORD_HASH", "scrypt-v1$" + "00" * 16 + "$" + "00" * 32)
    return monkeypatch


def test_vercel_ingress_keeps_anonymous_timetable_closed_without_database(hosted):
    with TestClient(
        create_vercel_app(), base_url="http://student.test", headers=FORWARDED
    ) as client:
        assert client.get("/health/live").status_code == 200
        for path in [
            "/api/v1/status",
            "/auth/",
            "/openapi.json",
            "/ops/health",
            "/api//v1/rooms/1",
        ]:
            response = client.get(path)
            assert response.status_code == 401, path
            assert response.headers["cache-control"] == "private, no-store"
        assert client.get("/auth/session").json() == {
            "mode": "beta",
            "authenticated": False,
            "needs_renewal": False,
        }


@pytest.mark.parametrize(
    "change", ["missing_platform", "http", "missing_ip", "ip_list", "bad_ip", "host"]
)
def test_vercel_rejects_untrusted_transport_and_aliases(hosted, change):
    headers = FORWARDED.copy()
    address = "http://student.test"
    if change == "missing_platform":
        hosted.delenv("VERCEL")
    elif change == "http":
        headers["x-forwarded-proto"] = "http"
    elif change == "missing_ip":
        headers.pop("x-vercel-forwarded-for")
    elif change == "ip_list":
        headers["x-vercel-forwarded-for"] = "192.0.2.1, 192.0.2.2"
    elif change == "bad_ip":
        headers["x-vercel-forwarded-for"] = "anything"
    else:
        address = "https://other.vercel.app"
    with TestClient(create_vercel_app(), base_url=address) as client:
        response = client.get("/auth/session", headers=headers)
        assert response.status_code in {403, 421, 503}
        assert response.headers["cache-control"] == "private, no-store"
        assert "csrf" not in response.text


@pytest.mark.parametrize("change", ["ssl", "pool", "local", "admin"])
def test_bad_hosted_configuration_fails_closed_but_liveness_survives(hosted, change):
    if change == "ssl":
        hosted.setenv("DATABASE_URL", "postgresql://reader@host/db")
    elif change == "pool":
        hosted.setenv("DATABASE_POOL_MODE", "session")
    elif change == "local":
        hosted.setenv("STUDENT_AUTH_ORIGIN", "http://127.0.0.1:5173")
    else:
        hosted.setenv("MIGRATION_DATABASE_URL", "postgresql://admin@host/db")
    with TestClient(create_vercel_app(), base_url=ORIGIN, headers=FORWARDED) as client:
        assert client.get("/health/live").status_code == 200
        response = client.get("/auth/session")
        assert response.status_code == 503
        assert "admin@" not in response.text


def test_only_platform_ip_is_used_for_shared_rate_limits(hosted):
    seen = []

    def limited(self, request, purpose, email=""):
        seen.append(request.client.host)
        raise APIError(429, "rate_limited", "Try later.")

    hosted.setattr(StudentAuth, "limit", limited)
    with TestClient(create_vercel_app(), base_url=ORIGIN, headers=FORWARDED) as client:
        response = client.post(
            "/auth/beta",
            json={"passcode": "synthetic-test-passcode"},
            headers={"Origin": ORIGIN, "X-Student-Request": "1", "x-forwarded-for": "203.0.113.9"},
        )
        assert response.status_code == 429
    assert seen == ["192.0.2.2"]
