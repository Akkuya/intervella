import asyncio

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings


@pytest.mark.parametrize(
    "values",
    [
        {"freshness_max_age_hours": 0},
        {"freshness_max_age_hours": float("inf")},
        {"freshness_max_age_hours": float("nan")},
        {"max_availability_limit": 0},
        {"max_availability_limit": 101},
        {"request_timeout_seconds": 3},
        {"request_timeout_seconds": float("nan")},
        {"allowed_origins": ("*",)},
        {"allowed_origins": ("https://example.test/path",)},
        {"allowed_origins": ("https://user:password@example.test",)},
    ],
)
def test_settings_reject_invalid_boundaries(values):
    with pytest.raises(ValueError):
        Settings(**values)


def test_settings_read_environment(monkeypatch):
    monkeypatch.setenv("FRESHNESS_MAX_AGE_HOURS", "12")
    monkeypatch.setenv("MAX_AVAILABILITY_LIMIT", "20")
    monkeypatch.setenv("API_REQUEST_TIMEOUT_SECONDS", "10")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://one.test, http://localhost:5173")
    settings = Settings.from_environment()
    assert settings.freshness_max_age_hours == 12
    assert settings.max_availability_limit == 20
    assert settings.request_timeout_seconds == 10
    assert settings.allowed_origins == ("https://one.test", "http://localhost:5173")


def test_settings_errors_do_not_reflect_environment(monkeypatch):
    monkeypatch.setenv("FRESHNESS_MAX_AGE_HOURS", "private-value")
    with pytest.raises(ValueError) as error:
        Settings.from_environment()
    assert "private-value" not in str(error.value)


def test_http_errors_and_unexpected_errors_are_safe(caplog):
    app = create_app(Settings(allowed_origins=("https://example.test",)))

    @app.get("/test-error")
    def broken():
        raise RuntimeError("password=do-not-log")

    with TestClient(app) as client:
        error = client.get(
            "/test-error", headers={"X-Request-ID": "untrusted", "Origin": "https://example.test"}
        )
        assert error.status_code == 500
        assert error.json()["error"]["code"] == "internal_error"
        assert error.headers["x-request-id"] != "untrusted"
        assert error.headers["access-control-allow-origin"] == "https://example.test"
        assert "do-not-log" not in error.text and "do-not-log" not in caplog.text
        missing = client.get("/unknown")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "not_found"
        wrong_method = client.post("/health/live")
        assert wrong_method.status_code == 405
        assert wrong_method.json()["error"]["code"] == "method_not_allowed"


def test_request_timeout_uses_error_contract():
    app = create_app(
        Settings(request_timeout_seconds=3.01, allowed_origins=("https://example.test",))
    )

    @app.get("/test-slow")
    async def slow():
        await asyncio.sleep(5)
        return {"status": "late"}

    with TestClient(app) as client:
        response = client.get("/test-slow", headers={"Origin": "https://example.test"})
        assert response.status_code == 504
        assert response.json()["error"]["code"] == "request_timeout"
        assert response.headers["x-request-id"]
        assert response.headers["access-control-allow-origin"] == "https://example.test"
