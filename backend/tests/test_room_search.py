from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from schedule_helpers import DAY_END, NOW, make_schedule

from app import db
from app.main import create_app, utc_now
from app.settings import Settings


@pytest.fixture
def client(postgres_engine, monkeypatch):
    monkeypatch.setattr(db, "get_engine", lambda: postgres_engine)
    app = create_app(Settings())
    app.dependency_overrides[utc_now] = lambda: NOW
    with TestClient(app) as client:
        yield client


def search(client, **params):
    return client.get("/api/v1/room-search", params={"start": NOW.isoformat(), **params})


@pytest.mark.postgres
def test_search_proves_free_until_and_preserves_unknown_and_inactive(client, postgres_engine):
    make_schedule(postgres_engine)
    result = search(client, include_next=True, room_ids=[1, 2, 3, 4, 5, 7, 999])
    assert result.status_code == 200
    body = result.json()
    rooms = {room["room_id"]: room for room in body["data"]}
    assert rooms[1]["state"] == "available"
    assert rooms[1]["available_until"] == (NOW + timedelta(hours=1)).isoformat().replace(
        "+00:00", "Z"
    )
    assert rooms[2]["available_until"] == DAY_END.isoformat().replace("+00:00", "Z")
    assert rooms[2]["next_booking"] is None
    assert all(rooms[i]["state"] == "unknown" for i in [3, 4, 5])
    assert rooms[7]["state"] == "inactive" and rooms[7]["available_until"] is None
    assert body["meta"]["missing_room_ids"] == [999]


@pytest.mark.postgres
def test_until_boundary_next_opening_and_normalized_name(client, postgres_engine):
    make_schedule(postgres_engine)
    exact = search(client, end=(NOW + timedelta(hours=1)).isoformat(), room_name="a101").json()
    assert [room["room_id"] for room in exact["data"]] == [1]
    later = search(client, duration_minutes=61, room_name="A-101", include_next=True).json()
    room = later["data"][0]
    assert room["state"] == "scheduled"
    assert room["available_until"] is None
    assert room["next_available_start"] == (NOW + timedelta(hours=3)).isoformat().replace(
        "+00:00", "Z"
    )


@pytest.mark.postgres
@pytest.mark.parametrize(
    "params",
    [
        {"end": NOW.isoformat()},
        {"end": (NOW + timedelta(hours=5)).isoformat()},
        {"end": (NOW + timedelta(hours=1)).isoformat(), "duration_minutes": 30},
        {"start": "2026-10-14T08:00:00"},
        {"sort": "SQL"},
        {"room_ids": [0]},
        {"room_ids": list(range(1, 102))},
        {"room_name": "%"},
        {"building": "NOPE"},
    ],
)
def test_search_validation(client, postgres_engine, params):
    make_schedule(postgres_engine)
    result = search(client, **params)
    assert result.status_code == 422
    assert set(result.json()) == {"error"}


@pytest.mark.postgres
def test_next_known_opening_never_bridges_gaps_or_uncertain_windows(client, postgres_engine):
    from sqlmodel import Session

    from app.models import RoomCoverage

    dataset = make_schedule(
        postgres_engine,
        published=False,
        active=False,
        meetings=[],
        coverage={
            1: (NOW, NOW + timedelta(minutes=30), "complete"),
            2: (NOW, DAY_END, "complete"),
        },
    )
    with Session(postgres_engine) as session, session.begin():
        session.add_all(
            [
                RoomCoverage(
                    dataset_id=dataset,
                    room_id=1,
                    starts_at=NOW + timedelta(hours=2),
                    ends_at=NOW + timedelta(hours=4),
                    completeness="complete",
                ),
                RoomCoverage(
                    dataset_id=dataset,
                    room_id=2,
                    starts_at=NOW + timedelta(minutes=20),
                    ends_at=NOW + timedelta(minutes=40),
                    completeness="unknown",
                ),
            ]
        )
        from app.models import Dataset

        record = session.get(Dataset, dataset)
        record.published_at = NOW
        session.add(record)
        session.flush()
        from app.models import DatasetState

        state = session.get(DatasetState, 1)
        state.active_dataset_id = dataset
        session.add(state)
    result = search(client, include_next=True).json()
    rooms = {room["room_id"]: room for room in result["data"]}
    assert rooms[1]["state"] == rooms[2]["state"] == "unknown"
    assert rooms[1]["next_available_start"] == (NOW + timedelta(hours=2)).isoformat().replace(
        "+00:00", "Z"
    )
    assert rooms[2]["next_available_start"] == (NOW + timedelta(minutes=40)).isoformat().replace(
        "+00:00", "Z"
    )
    assert rooms[1]["available_until"] is None


@pytest.mark.postgres
def test_sort_limit_staleness_and_horizon_are_explicit(client, postgres_engine):
    make_schedule(
        postgres_engine,
        fetched_at=NOW - timedelta(days=3),
        meetings=[],
        coverage={
            1: (NOW, NOW + timedelta(days=2), "complete"),
            2: (NOW, NOW + timedelta(hours=2), "complete"),
        },
    )
    body = search(client, sort="duration", limit=1).json()
    assert [room["room_id"] for room in body["data"]] == [1]
    assert body["meta"]["freshness"] == "stale" and body["meta"]["has_more"]
    assert body["data"][0]["available_until"] == body["meta"]["lookahead_end"]
    assert search(client, sort="room").json()["data"][0]["room_number"] == "101"


@pytest.mark.postgres
@pytest.mark.parametrize(
    "start,end",
    [
        ("2026-11-01T01:30:00-04:00", "2026-11-01T01:30:00-05:00"),
        ("2026-03-08T01:30:00-05:00", "2026-03-08T03:30:00-04:00"),
        ("2026-10-14T23:30:00-04:00", "2026-10-15T00:30:00-04:00"),
    ],
)
def test_until_uses_instants_through_dst_and_midnight(client, postgres_engine, start, end):
    from datetime import UTC, datetime

    left = datetime.fromisoformat(start).astimezone(UTC)
    right = datetime.fromisoformat(end).astimezone(UTC)
    make_schedule(
        postgres_engine, fetched_at=left, meetings=[], coverage={1: (left, right, "complete")}
    )
    client.app.dependency_overrides[utc_now] = lambda: left
    body = search(client, start=start, end=end).json()
    assert body["data"][0]["state"] == "available"
    assert body["data"][0]["available_until"] == right.isoformat().replace("+00:00", "Z")


@pytest.mark.postgres
def test_search_publication_race_stays_on_captured_dataset(client, postgres_engine):
    from sqlalchemy import event, text

    old = make_schedule(postgres_engine)
    new = make_schedule(postgres_engine, active=False, meetings=[])
    switched = []

    def switch(connection, cursor, statement, parameters, context, executemany):
        if not switched and statement.startswith("SELECT") and "dataset_state" in statement:
            switched.append(True)
            with postgres_engine.begin() as writer:
                writer.execute(
                    text("UPDATE utscvacant.dataset_state SET active_dataset_id=:id"), {"id": new}
                )

    event.listen(postgres_engine, "after_cursor_execute", switch)
    try:
        body = search(client, room_ids=[1]).json()
    finally:
        event.remove(postgres_engine, "after_cursor_execute", switch)
    assert body["meta"]["dataset_id"] == str(old)
    assert body["data"][0]["available_until"] == (NOW + timedelta(hours=1)).isoformat().replace(
        "+00:00", "Z"
    )


@pytest.mark.postgres
def test_search_scale_batches_and_payload_limits(client, postgres_engine, tmp_path, monkeypatch):
    from ingestion_helpers import write_large_bundle
    from sqlalchemy import event

    from app.ingest.pipeline import import_directory, publish_dataset
    from app.services import room_search

    write_large_bundle(tmp_path)
    staged = import_directory(postgres_engine, tmp_path)
    publish_dataset(postgres_engine, staged["dataset_id"])
    selects = []

    def count(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("SELECT"):
            selects.append(statement)

    event.listen(postgres_engine, "before_cursor_execute", count)
    try:
        result = search(client, include_next=True)
    finally:
        event.remove(postgres_engine, "before_cursor_execute", count)
    assert result.status_code == 200 and len(result.json()["data"]) == 67
    assert len(selects) <= 6
    monkeypatch.setattr(room_search, "MAX_RECORDS", 1)
    assert search(client).json()["error"]["code"] == "search_too_large"
