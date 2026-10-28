from datetime import timedelta

import pytest
from schedule_helpers import DAY_END, DAY_START, NOW, make_schedule
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session

from app.errors import APIError
from app.services import availability

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize(
    "meeting_start,meeting_end,expected",
    [
        (-60, 0, True),
        (60, 120, True),
        (0, 60, False),
        (-10, 10, False),
        (50, 70, False),
        (-60, 120, False),
        (10, 20, False),
    ],
)
def test_half_open_overlap(postgres_engine, meeting_start, meeting_end, expected):
    make_schedule(
        postgres_engine,
        meetings=[
            (
                1,
                NOW + timedelta(minutes=meeting_start),
                NOW + timedelta(minutes=meeting_end),
                "scheduled",
            )
        ],
    )
    with Session(postgres_engine) as session:
        result = availability.find_available_rooms(
            session, start=NOW, end=NOW + timedelta(hours=1), now=NOW
        )
    assert (1 in [room.room_id for room in result.data]) is expected


def test_coverage_cancellations_next_booking_and_order(postgres_engine):
    dataset = make_schedule(postgres_engine)
    with Session(postgres_engine) as session:
        result = availability.find_available_rooms(
            session, start=NOW, end=NOW + timedelta(hours=1), now=NOW
        )
        assert [room.room_id for room in result.data] == [1, 2, 6]
        assert result.data[0].next_booking == NOW + timedelta(hours=1)
        assert result.data[1].next_booking is None
        assert result.meta.dataset_id == dataset
        assert result.meta.unknown_room_count == 3
        assert result.meta.coverage == "partial"
        busy = availability.find_available_rooms(
            session, start=NOW + timedelta(hours=1), end=NOW + timedelta(hours=2), now=NOW
        )
        assert [room.room_id for room in busy.data] == [2, 6]


def test_building_limit_and_has_more(postgres_engine):
    make_schedule(postgres_engine)
    with Session(postgres_engine) as session:
        result = availability.find_available_rooms(
            session, start=NOW, end=NOW + timedelta(minutes=5), now=NOW, building="A", limit=1
        )
        assert [room.room_id for room in result.data] == [1]
        assert result.meta.has_more is True
        only_b = availability.find_available_rooms(
            session, start=NOW, end=NOW + timedelta(minutes=5), now=NOW, building="B"
        )
        assert [room.room_id for room in only_b.data] == [6]
        assert only_b.meta.unknown_room_count == 0


@pytest.mark.parametrize("age,expected", [(36, "fresh"), (36.001, "stale")])
def test_freshness_threshold(postgres_engine, age, expected):
    make_schedule(postgres_engine, fetched_at=NOW - timedelta(hours=age))
    with Session(postgres_engine) as session:
        result = availability.find_available_rooms(
            session, start=NOW, end=NOW + timedelta(minutes=5), now=NOW
        )
        assert result.meta.freshness == expected
        assert bool(result.meta.warnings) == (expected == "stale")


def test_partial_window_is_not_complete_coverage(postgres_engine):
    make_schedule(
        postgres_engine,
        coverage={
            1: (NOW, NOW + timedelta(minutes=30), "complete"),
            2: (DAY_START, DAY_END, "complete"),
        },
        meetings=[],
    )
    with Session(postgres_engine) as session:
        result = availability.find_available_rooms(
            session, start=NOW, end=NOW + timedelta(hours=1), now=NOW
        )
        assert [room.room_id for room in result.data] == [2]


@pytest.mark.parametrize(
    "coverage,code",
    [
        ({}, "coverage_unavailable"),
        (
            {1: (DAY_START, NOW, "complete"), 2: (NOW + timedelta(hours=1), DAY_END, "complete")},
            "coverage_unavailable",
        ),
        ({1: (DAY_START, DAY_END, "partial")}, "coverage_unavailable"),
    ],
)
def test_missing_complete_coverage_and_cross_room_gaps_are_unavailable(
    postgres_engine, coverage, code
):
    make_schedule(postgres_engine, coverage=coverage, meetings=[])
    with Session(postgres_engine) as session, pytest.raises(APIError) as error:
        availability.find_available_rooms(
            session, start=NOW, end=NOW + timedelta(minutes=30), now=NOW
        )
    assert error.value.status_code == 503
    assert error.value.code == code


def test_outside_dataset_period_is_explicit_error(postgres_engine):
    make_schedule(postgres_engine)
    with Session(postgres_engine) as session, pytest.raises(APIError) as error:
        availability.find_available_rooms(
            session, start=NOW + timedelta(days=2), end=NOW + timedelta(days=2, hours=1), now=NOW
        )
    assert error.value.status_code == 422
    assert error.value.code == "outside_dataset_coverage"


def test_all_busy_is_valid_empty_result(postgres_engine):
    make_schedule(postgres_engine, coverage={1: (DAY_START, DAY_END, "complete")})
    with Session(postgres_engine) as session:
        result = availability.find_available_rooms(
            session, start=NOW + timedelta(hours=1), end=NOW + timedelta(hours=2), now=NOW
        )
    assert result.data == []
    assert result.meta.has_more is False


def test_next_booking_ignores_cancelled_meetings(postgres_engine):
    make_schedule(
        postgres_engine,
        meetings=[
            (1, NOW + timedelta(hours=1), NOW + timedelta(hours=2), "cancelled"),
            (1, NOW + timedelta(hours=2), NOW + timedelta(hours=3), "scheduled"),
        ],
    )
    with Session(postgres_engine) as session:
        result = availability.find_available_rooms(
            session, start=NOW, end=NOW + timedelta(minutes=5), now=NOW
        )
    assert result.data[0].next_booking == NOW + timedelta(hours=2)


def test_api_session_enforces_read_only_snapshot(postgres_engine, monkeypatch):
    from app import db

    monkeypatch.setattr(db, "get_engine", lambda: postgres_engine)
    dependency = db.get_read_session()
    session = next(dependency)
    try:
        assert session.scalar(text("SHOW transaction_isolation")) == "repeatable read"
        assert session.scalar(text("SHOW transaction_read_only")) == "on"
        with pytest.raises(DBAPIError):
            session.execute(
                text("INSERT INTO utscvacant.buildings (code,name) VALUES ('DENIED','Denied')")
            )
    finally:
        dependency.close()


def test_publication_race_keeps_metadata_coverage_and_rooms_in_one_snapshot(
    postgres_engine, monkeypatch
):
    from app import db

    old = make_schedule(postgres_engine)
    new = make_schedule(
        postgres_engine,
        active=False,
        fetched_at=NOW - timedelta(hours=48),
        meetings=[],
        coverage={1: (DAY_START, DAY_END, "complete")},
    )
    switched = []

    def publish_after_capture(connection, cursor, statement, parameters, context, executemany):
        if (
            not switched
            and statement.lstrip().upper().startswith("SELECT")
            and "dataset_state" in statement
        ):
            switched.append(True)
            with postgres_engine.begin() as writer:
                writer.execute(
                    text("UPDATE utscvacant.dataset_state SET active_dataset_id=:id WHERE id=1"),
                    {"id": new},
                )
                writer.execute(text("UPDATE utscvacant.rooms SET active=false WHERE id=2"))

    monkeypatch.setattr(db, "get_engine", lambda: postgres_engine)
    event.listen(postgres_engine, "after_cursor_execute", publish_after_capture)
    dependency = db.get_read_session()
    session = next(dependency)
    try:
        result = availability.find_available_rooms(
            session, start=NOW + timedelta(hours=1), end=NOW + timedelta(hours=2), now=NOW
        )
        assert switched
        assert result.meta.dataset_id == old
        assert result.meta.source_fetched_at == NOW
        assert result.meta.freshness == "fresh"
        assert result.meta.unknown_room_count == 3
        assert [room.room_id for room in result.data] == [2, 6]
    finally:
        dependency.close()
        event.remove(postgres_engine, "after_cursor_execute", publish_after_capture)
    with Session(postgres_engine) as session:
        assert availability.active_dataset(session).id == new
