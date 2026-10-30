"""Synthetic API fixtures, separate from the immutable development seed."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlmodel import Session
from sqlalchemy import text

from app.models import (
    Building,
    Dataset,
    DatasetState,
    IngestionRun,
    MeetingOccurrence,
    Room,
    RoomCoverage,
)

NOW = datetime(2026, 10, 14, 12, tzinfo=UTC)
DAY_START = NOW.replace(hour=4)
DAY_END = DAY_START + timedelta(days=1)


def activate_schedule(connection, dataset_id):
    """Mirror publication in fixtures, including tests deliberately using old schemas."""
    connection.execute(text("UPDATE utscvacant.dataset_state SET active_dataset_id=:id WHERE id=1"), {"id": dataset_id})
    if connection.scalar(text("SELECT to_regclass('utscvacant.active_periods')")):
        connection.execute(text("""
            INSERT INTO utscvacant.active_periods (start_date,end_date,dataset_id)
            SELECT (min(starts_at) AT TIME ZONE 'America/Toronto')::date,
                   ((max(ends_at)-interval '1 microsecond') AT TIME ZONE 'America/Toronto')::date+1,
                   :id FROM utscvacant.room_coverage WHERE dataset_id=:id
            ON CONFLICT(start_date) DO UPDATE SET end_date=excluded.end_date,dataset_id=excluded.dataset_id
        """), {"id": dataset_id})


def make_schedule(
    engine, *, fetched_at=NOW, coverage=None, meetings=None, active=True, published=True
):
    with Session(engine) as session, session.begin():
        if session.get(Building, 1) is None:
            session.add_all(
                [
                    Building(id=1, code="A", name="Synthetic A"),
                    Building(id=2, code="B", name="Synthetic B"),
                ]
            )
            session.flush()
            session.add_all(
                [
                    Room(
                        id=i,
                        building_id=1 if i <= 5 else 2,
                        room_number=str(100 + i),
                        active=i != 7,
                    )
                    for i in range(1, 8)
                ]
            )
            session.flush()
        run = IngestionRun(
            started_at=fetched_at, finished_at=fetched_at, status="succeeded", input_hash="a" * 64
        )
        session.add(run)
        session.flush()
        dataset = Dataset(run_id=run.id, source_fetched_at=fetched_at)
        session.add(dataset)
        session.flush()
        if coverage is None:
            coverage = {
                i: (DAY_START, DAY_END, status)
                for i, status in [
                    (1, "complete"),
                    (2, "complete"),
                    (3, "partial"),
                    (4, "unknown"),
                    (6, "complete"),
                    (7, "complete"),
                ]
            }
        for room_id, (start, end, status) in coverage.items():
            session.execute(text("""INSERT INTO utscvacant.room_coverage
                (dataset_id,room_id,starts_at,ends_at,completeness) VALUES (:dataset,:room,:start,:end,:status)"""),
                {"dataset": dataset.id, "room": room_id, "start": start, "end": end, "status": status})
        if meetings is None:
            meetings = [
                (1, NOW + timedelta(hours=1), NOW + timedelta(hours=2), "scheduled"),
                (1, NOW + timedelta(hours=2), NOW + timedelta(hours=3), "scheduled"),
                (2, NOW + timedelta(hours=1), NOW + timedelta(hours=2), "cancelled"),
            ]
        for room_id, start, end, status in meetings:
            session.add(
                MeetingOccurrence(
                    dataset_id=dataset.id,
                    room_id=room_id,
                    source_key=str(uuid4()),
                    starts_at=start,
                    ends_at=end,
                    status=status,
                )
            )
        session.flush()
        if published:
            dataset.published_at = fetched_at + timedelta(seconds=1)
            session.add(dataset)
            session.flush()
        if active:
            activate_schedule(session.connection(), dataset.id)
        return dataset.id
