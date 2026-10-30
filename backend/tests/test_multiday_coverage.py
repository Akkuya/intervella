from datetime import timedelta

import pytest
from schedule_helpers import DAY_END, DAY_START, NOW, make_schedule
from sqlmodel import Session

from app.models import RoomCoverage
from app.services.availability import find_available_rooms, room_schedule

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("gap", [0, 1])
def test_complete_windows_union_without_bridging_gaps(postgres_engine, gap):
    dataset = make_schedule(
        postgres_engine,
        coverage={1: (DAY_START, NOW, "complete"), 2: (DAY_START, DAY_END, "complete")},
        meetings=[],
        published=False,
        active=False,
    )
    with Session(postgres_engine) as session, session.begin():
        session.add(
            RoomCoverage(
                dataset_id=dataset,
                room_id=1,
                starts_at=NOW + timedelta(minutes=gap),
                ends_at=DAY_END,
                completeness="complete",
            )
        )
    from sqlalchemy import text

    with postgres_engine.begin() as connection:
        connection.execute(
            text("UPDATE utscvacant.datasets SET published_at=:now WHERE id=:id"),
            {"now": NOW, "id": dataset},
        )
        connection.execute(
            text("UPDATE utscvacant.dataset_state SET active_dataset_id=:id"), {"id": dataset}
        )
    with Session(postgres_engine) as session:
        result = find_available_rooms(
            session, start=NOW - timedelta(minutes=5), end=NOW + timedelta(minutes=5), now=NOW
        )
        assert (1 in [room.room_id for room in result.data]) is (gap == 0)
        assert result.meta.unknown_room_count == (4 if gap == 0 else 5)
        day = room_schedule(session, 1, NOW.date(), NOW)
        assert day.meta.coverage.completeness == ("complete" if gap == 0 else "partial")


def test_day_summary_ignores_other_days(postgres_engine):
    dataset = make_schedule(postgres_engine, meetings=[], published=False, active=False)
    with Session(postgres_engine) as session, session.begin():
        session.add(
            RoomCoverage(
                dataset_id=dataset,
                room_id=1,
                starts_at=DAY_END,
                ends_at=DAY_END + timedelta(days=1),
                completeness="unknown",
            )
        )
    from sqlalchemy import text

    with postgres_engine.begin() as connection:
        connection.execute(
            text("UPDATE utscvacant.datasets SET published_at=:now WHERE id=:id"),
            {"now": NOW, "id": dataset},
        )
        connection.execute(
            text("UPDATE utscvacant.dataset_state SET active_dataset_id=:id"), {"id": dataset}
        )
    with Session(postgres_engine) as session:
        assert room_schedule(session, 1, NOW.date(), NOW).meta.coverage.completeness == "complete"
        assert (
            room_schedule(session, 1, DAY_END.date(), NOW).meta.coverage.completeness == "unknown"
        )


def test_migration_preserves_rows_and_refuses_lossy_downgrade(postgres_engine):
    from alembic import command
    from conftest import migration_config
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    with postgres_engine.begin() as connection:
        command.downgrade(migration_config(connection), "0001")
    dataset = make_schedule(postgres_engine)
    with postgres_engine.begin() as connection:
        before = connection.execute(text("SELECT * FROM utscvacant.room_coverage")).all()
        command.upgrade(migration_config(connection), "head")
        assert connection.execute(text("SELECT * FROM utscvacant.room_coverage")).all() == before
        command.check(migration_config(connection))
    with Session(postgres_engine) as session:
        assert session.get(RoomCoverage, (dataset, 1, DAY_START)) is not None
    candidate_id = make_schedule(postgres_engine, active=False, published=False)
    with Session(postgres_engine) as session, session.begin():
        session.add(
            RoomCoverage(
                dataset_id=candidate_id,
                room_id=1,
                starts_at=DAY_END,
                ends_at=DAY_END + timedelta(days=1),
                completeness="unknown",
            )
        )
    with pytest.raises(DBAPIError), postgres_engine.begin() as connection:
        command.downgrade(migration_config(connection), "0001")
    with postgres_engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0003"


def test_conflicting_unknown_window_is_not_overridden_by_complete_window(postgres_engine):
    dataset = make_schedule(postgres_engine, meetings=[], active=False, published=False)
    with Session(postgres_engine) as session, session.begin():
        session.add(
            RoomCoverage(
                dataset_id=dataset,
                room_id=1,
                starts_at=NOW,
                ends_at=NOW + timedelta(minutes=30),
                completeness="unknown",
            )
        )
    from sqlalchemy import text

    with postgres_engine.begin() as connection:
        connection.execute(
            text("UPDATE utscvacant.datasets SET published_at=:now WHERE id=:id"),
            {"now": NOW, "id": dataset},
        )
        connection.execute(
            text("UPDATE utscvacant.dataset_state SET active_dataset_id=:id"), {"id": dataset}
        )
    with Session(postgres_engine) as session:
        result = find_available_rooms(session, start=NOW, end=NOW + timedelta(minutes=30), now=NOW)
        assert 1 not in [room.room_id for room in result.data]
        assert room_schedule(session, 1, NOW.date(), NOW).meta.coverage.completeness == "partial"
