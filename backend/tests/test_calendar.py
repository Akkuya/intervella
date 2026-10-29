from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from ingestion_helpers import write_large_bundle
from schedule_helpers import DAY_END, DAY_START, NOW, make_schedule
from sqlalchemy import event

from app import db
from app.ingest.pipeline import import_directory, publish_dataset
from app.main import create_app, utc_now
from app.schemas import CoverageWindow, MeetingInfo
from app.services.calendar import day_calendar
from app.settings import Settings


def coverage(start, end, status="complete"):
    return CoverageWindow(starts_at=start, ends_at=end, completeness=status)


def test_calendar_never_bridges_gaps_and_cancellations_do_not_occupy():
    windows = [
        coverage(NOW, NOW + timedelta(hours=1)),
        coverage(NOW + timedelta(hours=2), NOW + timedelta(hours=3)),
    ]
    meetings = [
        MeetingInfo(id=1, starts_at=NOW, ends_at=NOW + timedelta(minutes=30), status="cancelled"),
        MeetingInfo(
            id=2,
            starts_at=NOW + timedelta(minutes=30),
            ends_at=NOW + timedelta(hours=1),
            status="scheduled",
        ),
    ]
    result = day_calendar(DAY_START, DAY_END, windows, meetings)
    assert result.window.start == NOW
    assert result.window.end == NOW + timedelta(hours=3)
    assert [period.state for period in result.periods] == [
        "available",
        "scheduled",
        "unknown",
        "available",
    ]
    assert result.periods[2].starts_at == NOW + timedelta(hours=1)


def test_unknown_overrides_complete_and_known_booking_remains_occupied():
    windows = [
        coverage(NOW, NOW + timedelta(hours=1)),
        coverage(NOW, NOW + timedelta(minutes=30), "unknown"),
    ]
    result = day_calendar(DAY_START, DAY_END, windows, [])
    assert [period.state for period in result.periods] == ["unknown", "available"]
    empty = day_calendar(DAY_START, DAY_END, [], [])
    assert empty.window.start == DAY_START and empty.window.end == DAY_END
    assert [period.state for period in empty.periods] == ["unknown"]


def test_calendar_overlaps_adjacency_and_midnight_clip_correctly():
    meetings = [
        MeetingInfo(
            id=i,
            starts_at=DAY_START + timedelta(minutes=left),
            ends_at=DAY_START + timedelta(minutes=right),
            status="scheduled",
        )
        for i, (left, right) in enumerate([(-30, 30), (20, 45), (45, 60)], 1)
    ]
    result = day_calendar(
        DAY_START, DAY_END, [coverage(DAY_START, DAY_START + timedelta(hours=2))], meetings
    )
    assert result.periods[0].state == "scheduled"
    assert result.periods[0].starts_at == DAY_START
    assert result.periods[0].ends_at == DAY_START + timedelta(hours=1)
    assert result.periods[1].state == "available"


@pytest.mark.parametrize("day,hours", [("2026-03-08", 23), ("2026-11-01", 25)])
def test_calendar_day_geometry_uses_actual_dst_instants(day, hours):
    from datetime import date

    from app.services.availability import campus_day_bounds

    start, end = campus_day_bounds(date.fromisoformat(day))
    result = day_calendar(start, end, [coverage(start, end)], [])
    assert (result.window.end - result.window.start).total_seconds() == hours * 3600
    assert [period.state for period in result.periods] == ["available"]


@pytest.fixture
def client(postgres_engine, monkeypatch):
    monkeypatch.setattr(db, "get_engine", lambda: postgres_engine)
    app = create_app(Settings())
    app.dependency_overrides[utc_now] = lambda: NOW
    with TestClient(app) as client:
        yield client


@pytest.mark.postgres
def test_building_batch_and_room_calendar_share_contract(client, postgres_engine):
    dataset = make_schedule(postgres_engine)
    response = client.get("/api/v1/buildings/A/schedule", params={"date": "2026-10-14"})
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["dataset_id"] == str(dataset)
    assert len(body["data"]) == 5  # inactive room 7 and other building excluded
    assert [item["room"]["room_number"] for item in body["data"]] == [
        "101",
        "102",
        "103",
        "104",
        "105",
    ]
    assert body["data"][4]["calendar"]["periods"][0]["state"] == "unknown"
    room = client.get("/api/v1/rooms/1/schedule", params={"date": "2026-10-14"}).json()
    assert room["calendar"] == body["data"][0]["calendar"]
    assert room["data"][0]["public_label"] is None
    assert body["meta"]["unknown_room_count"] == 3


@pytest.mark.postgres
@pytest.mark.parametrize(
    "code,date,status",
    [
        ("NOPE", "2026-10-14", 404),
        ("A", "bad", 422),
        ("A", "2026-02-30", 422),
        ("A", "2026-11-30", 422),
    ],
)
def test_building_calendar_validation(client, postgres_engine, code, date, status):
    make_schedule(postgres_engine)
    result = client.get(f"/api/v1/buildings/{code}/schedule", params={"date": date})
    assert result.status_code == status
    assert set(result.json()) == {"error"}


@pytest.mark.postgres
def test_building_calendar_batches_large_inventory_without_room_query_fanout(
    client, postgres_engine, tmp_path
):
    write_large_bundle(tmp_path)
    staged = import_directory(postgres_engine, tmp_path)
    publish_dataset(postgres_engine, staged["dataset_id"])
    statements = []

    def record(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("SELECT"):
            statements.append(statement)

    event.listen(postgres_engine, "before_cursor_execute", record)
    try:
        result = client.get("/api/v1/buildings/SYN-0/schedule", params={"date": "2026-10-14"})
    finally:
        event.remove(postgres_engine, "before_cursor_execute", record)
    assert result.status_code == 200
    assert len(result.json()["data"]) == 7
    assert len(statements) <= 6
    assert result.json()["display_window"]["start"] == "2026-10-14T12:00:00Z"
    assert result.json()["display_window"]["end"] == "2026-10-14T14:00:00Z"


@pytest.mark.postgres
def test_building_calendar_is_bounded(client, postgres_engine, monkeypatch):
    from app.services import calendar

    make_schedule(postgres_engine)
    monkeypatch.setattr(calendar, "MAX_RECORDS", 1)
    result = client.get("/api/v1/buildings/A/schedule", params={"date": "2026-10-14"})
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "schedule_too_large"


@pytest.mark.postgres
def test_building_calendar_publication_race_uses_one_snapshot(client, postgres_engine):
    from sqlalchemy import text

    old = make_schedule(postgres_engine)
    new = make_schedule(
        postgres_engine, active=False, meetings=[], coverage={1: (DAY_START, DAY_END, "complete")}
    )
    switched = []

    def after_capture(connection, cursor, statement, parameters, context, executemany):
        if not switched and statement.startswith("SELECT") and "dataset_state" in statement:
            switched.append(True)
            with postgres_engine.begin() as writer:
                writer.execute(
                    text("UPDATE utscvacant.dataset_state SET active_dataset_id=:id"), {"id": new}
                )

    event.listen(postgres_engine, "after_cursor_execute", after_capture)
    try:
        result = client.get("/api/v1/buildings/A/schedule", params={"date": "2026-10-14"}).json()
    finally:
        event.remove(postgres_engine, "after_cursor_execute", after_capture)
    assert result["meta"]["dataset_id"] == str(old)
    assert len(result["data"][0]["meetings"]) == 2
    assert result["meta"]["unknown_room_count"] == 3


@pytest.mark.postgres
def test_inactive_room_keeps_timing_history_without_available_calendar_claim(
    client, postgres_engine
):
    make_schedule(postgres_engine)
    result = client.get("/api/v1/rooms/7/schedule", params={"date": "2026-10-14"}).json()
    assert result["room"]["active"] is False
    assert all(period["state"] != "available" for period in result["calendar"]["periods"])
