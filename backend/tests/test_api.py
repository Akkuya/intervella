from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from schedule_helpers import NOW, make_schedule
from sqlalchemy.exc import OperationalError

from app import db, seed
from app.main import create_app, utc_now
from app.settings import Settings

pytestmark = pytest.mark.usefixtures("authenticated_student")


@pytest.fixture
def client(postgres_engine, monkeypatch):
    monkeypatch.setattr(db, "get_engine", lambda: postgres_engine)
    app = create_app(Settings())
    app.dependency_overrides[utc_now] = lambda: NOW
    with TestClient(app) as client:
        yield client


@pytest.mark.postgres
def test_availability_contract(client, postgres_engine):
    dataset = make_schedule(postgres_engine)
    response = client.get("/api/v1/availability", params={"start": NOW.isoformat()})
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == {
        "start": "2026-10-14T12:00:00Z",
        "end": "2026-10-14T13:00:00Z",
        "timezone": "America/Toronto",
    }
    assert [room["room_id"] for room in body["data"]] == [1, 2, 6]
    assert body["data"][0]["next_booking"] == "2026-10-14T13:00:00Z"
    assert body["meta"]["dataset_id"] == str(dataset)
    assert body["meta"]["unknown_room_count"] == 3
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-request-id"]


@pytest.mark.postgres
@pytest.mark.parametrize(
    "query,field",
    [
        ({}, "start"),
        ({"start": "2026-10-14T12:00:00"}, "start"),
        ({"start": "1700000000"}, "start"),
        ({"duration_minutes": 4}, "duration_minutes"),
        ({"duration_minutes": 241}, "duration_minutes"),
        ({"duration_minutes": "5.5"}, "duration_minutes"),
        ({"limit": 0}, "limit"),
        ({"limit": 101}, "limit"),
        ({"building": "A'; DROP TABLE rooms;--"}, "building"),
        ({"start": (NOW - timedelta(minutes=5, microseconds=1)).isoformat()}, "start"),
        ({"start": (NOW + timedelta(days=30, microseconds=1)).isoformat()}, "start"),
        ({"start": "9999-12-31T23:59:59Z"}, "start"),
    ],
)
def test_invalid_queries_have_safe_errors(client, postgres_engine, query, field):
    make_schedule(postgres_engine)
    params = {"start": NOW.isoformat(), **query} if query else {}
    response = client.get("/api/v1/availability", params=params)
    assert response.status_code == 422
    error = response.json()["error"]
    assert field in error["fields"]
    assert error["request_id"] == response.headers["x-request-id"]
    assert "DROP" not in response.text and "sqlalchemy" not in response.text


@pytest.mark.postgres
def test_buildings_rooms_and_schedule(client, postgres_engine):
    make_schedule(postgres_engine)
    buildings = client.get("/api/v1/buildings")
    assert buildings.status_code == 200
    assert [row["code"] for row in buildings.json()["data"]] == ["A", "B"]
    room = client.get("/api/v1/rooms/1")
    assert room.json()["data"]["room_number"] == "101"
    assert client.get("/api/v1/rooms/999").status_code == 404
    assert client.get("/api/v1/rooms/0").status_code == 422
    assert client.get("/api/v1/rooms/1/schedule").status_code == 422
    schedule = client.get("/api/v1/rooms/2/schedule", params={"date": "2026-10-14"})
    assert schedule.status_code == 200
    assert schedule.json()["data"][0]["status"] == "cancelled"
    assert schedule.json()["meta"]["coverage"]["completeness"] == "complete"
    missing = client.get("/api/v1/rooms/5/schedule", params={"date": "2026-10-14"})
    assert missing.json()["data"] == []
    assert missing.json()["meta"]["coverage"]["completeness"] == "unknown"


@pytest.mark.postgres
def test_status_and_readiness(client, postgres_engine):
    assert client.get("/health/ready").status_code == 503
    assert client.get("/api/v1/status").status_code == 503
    make_schedule(postgres_engine, fetched_at=NOW - timedelta(hours=37))
    status = client.get("/api/v1/status")
    assert status.status_code == 200
    assert status.json()["degraded"] is True
    assert status.json()["age_seconds"] == 37 * 3600
    assert status.json()["freshness"] == "stale"
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["freshness"] == "stale"


def test_liveness_never_queries_database(monkeypatch):
    def forbidden():
        raise AssertionError("Liveness must not query database")

    monkeypatch.setattr(db, "get_engine", forbidden)
    response = TestClient(create_app(Settings())).get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_database_failures_are_sanitized(monkeypatch):
    def broken():
        raise OperationalError("SECRET SQL", {}, Exception("password=private"))

    monkeypatch.setattr(db, "get_engine", broken)
    with TestClient(create_app(Settings())) as client:
        for path in ["/health/ready", "/api/v1/status", "/api/v1/buildings", "/api/v1/rooms/1"]:
            response = client.get(path)
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "database_unavailable"
            assert "private" not in response.text and "SECRET" not in response.text


def test_cors_allowlist_and_openapi():
    with TestClient(create_app(Settings(allowed_origins=("https://example.test",)))) as client:
        allowed = client.get("/health/live", headers={"Origin": "https://example.test"})
        denied = client.get("/health/live", headers={"Origin": "https://evil.test"})
        assert allowed.headers["access-control-allow-origin"] == "https://example.test"
        assert "access-control-allow-origin" not in denied.headers
        schema = client.get("/openapi.json").json()
        expected = {
            "/api/v1/availability",
            "/api/v1/buildings",
            "/api/v1/buildings/{code}/schedule",
            "/api/v1/room-search",
            "/api/v1/rooms/{room_id}",
            "/api/v1/rooms/{room_id}/schedule",
            "/api/v1/status",
            "/health/live",
            "/health/ready",
            "/auth/session",
            "/auth/beta",
            "/auth/university/code",
            "/auth/university/verify",
            "/auth/renew",
            "/auth/logout",
        }
        assert set(schema["paths"]) == expected
        assert "ErrorResponse" in schema["components"]["schemas"]
        preflight = client.options(
            "/health/live",
            headers={
                "Origin": "https://example.test",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["x-request-id"]
        assert preflight.headers["access-control-allow-origin"] == "https://example.test"


@pytest.mark.postgres
def test_original_seed_through_api_with_controlled_clock(client, postgres_engine):
    seed.seed_synthetic(postgres_engine)
    response = client.get("/api/v1/availability", params={"start": NOW.isoformat()})
    assert response.status_code == 200
    assert [room["room_id"] for room in response.json()["data"]] == [1, 2]
    assert response.json()["meta"]["dataset_id"] == str(seed.CURRENT_DATASET)
    assert response.json()["meta"]["unknown_room_count"] == 3
    assert response.json()["data"][0]["next_booking"] == "2026-10-14T13:00:00Z"


@pytest.mark.postgres
def test_unpublished_candidate_never_affects_api(client, postgres_engine):
    published = make_schedule(postgres_engine)
    make_schedule(postgres_engine, active=False, published=False, meetings=[], coverage={})
    response = client.get("/api/v1/availability", params={"start": NOW.isoformat()})
    assert response.json()["meta"]["dataset_id"] == str(published)
    assert [room["room_id"] for room in response.json()["data"]] == [1, 2, 6]


@pytest.mark.postgres
@pytest.mark.parametrize(
    "date,start,end,hours",
    [
        (
            "2026-03-08",
            datetime(2026, 3, 8, 5, tzinfo=UTC),
            datetime(2026, 3, 9, 4, tzinfo=UTC),
            23,
        ),
        (
            "2026-11-01",
            datetime(2026, 11, 1, 4, tzinfo=UTC),
            datetime(2026, 11, 2, 5, tzinfo=UTC),
            25,
        ),
    ],
)
def test_schedule_dst_day_and_overnight_overlap(client, postgres_engine, date, start, end, hours):
    make_schedule(
        postgres_engine,
        coverage={1: (start, end, "complete")},
        meetings=[
            (1, start - timedelta(minutes=15), start, "scheduled"),
            (1, start - timedelta(minutes=15), start + timedelta(minutes=15), "scheduled"),
            (1, end - timedelta(minutes=15), end + timedelta(minutes=15), "scheduled"),
            (1, end, end + timedelta(hours=1), "scheduled"),
        ],
    )
    response = client.get("/api/v1/rooms/1/schedule", params={"date": date})
    assert response.status_code == 200
    body = response.json()
    assert len(body["data"]) == 2
    query_start = datetime.fromisoformat(body["query"]["start"])
    query_end = datetime.fromisoformat(body["query"]["end"])
    assert (query_end - query_start).total_seconds() == hours * 3600
    assert body["meta"]["coverage"]["completeness"] == "complete"


@pytest.mark.postgres
def test_no_complete_coverage_is_not_an_empty_availability_result(client, postgres_engine):
    make_schedule(
        postgres_engine, coverage={1: (NOW, NOW + timedelta(hours=1), "unknown")}, meetings=[]
    )
    response = client.get("/api/v1/availability", params={"start": NOW.isoformat()})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "coverage_unavailable"
    assert client.get("/health/ready").status_code == 503
    assert client.get("/api/v1/status").json()["degraded"] is True


@pytest.mark.postgres
def test_outside_coverage_and_expired_readiness(client, postgres_engine):
    make_schedule(
        postgres_engine,
        coverage={1: (NOW - timedelta(days=2), NOW - timedelta(days=1), "complete")},
    )
    response = client.get("/api/v1/availability", params={"start": NOW.isoformat()})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "outside_dataset_coverage"
    assert client.get("/health/ready").status_code == 503


@pytest.mark.postgres
def test_configured_freshness_and_query_cap(postgres_engine, monkeypatch):
    make_schedule(postgres_engine, fetched_at=NOW - timedelta(hours=2))
    monkeypatch.setattr(db, "get_engine", lambda: postgres_engine)
    app = create_app(Settings(freshness_max_age_hours=1, max_availability_limit=10))
    app.dependency_overrides[utc_now] = lambda: NOW
    with TestClient(app) as client:
        denied = client.get("/api/v1/availability", params={"start": NOW.isoformat(), "limit": 11})
        assert denied.status_code == 422
        allowed = client.get("/api/v1/availability", params={"start": NOW.isoformat(), "limit": 10})
        assert allowed.status_code == 200
        assert allowed.json()["meta"]["freshness"] == "stale"
        assert allowed.json()["meta"]["warnings"] == ["stale_dataset"]
        default = client.get("/api/v1/availability", params={"start": NOW.isoformat()})
        assert default.status_code == 200
