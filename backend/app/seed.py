"""Deterministic, synthetic-only development data. Never fetches a schedule source."""

import argparse
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from app.db import create_db_engine
from app.models import (
    ActivePeriod,
    Building,
    Dataset,
    DatasetState,
    IngestionRun,
    MeetingOccurrence,
    Room,
    RoomCoverage,
)

CURRENT_DATASET = UUID("00000000-0000-0000-0000-000000000202")
PREVIOUS_DATASET = UUID("00000000-0000-0000-0000-000000000201")
SOURCE_TIME = datetime(2026, 10, 14, 12, tzinfo=UTC)


def seed_synthetic(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        state = session.exec(
            select(DatasetState).where(DatasetState.id == 1).with_for_update()
        ).one()
        if session.get(Dataset, CURRENT_DATASET) is not None:
            return
        for model in (Building, Room, IngestionRun, Dataset, RoomCoverage, MeetingOccurrence):
            if session.exec(select(model).limit(1)).first() is not None:
                raise ValueError("Synthetic seed requires an empty migrated database")

        session.add_all(
            [
                Building(id=1, code="SYN-A", name="Synthetic Building A"),
                Building(id=2, code="SYN-B", name="Synthetic Building B"),
            ]
        )
        session.flush()
        session.add_all(
            [
                Room(
                    id=number,
                    building_id=1 if number <= 3 else 2,
                    room_number=str(100 + number),
                    capacity=20 if number == 1 else None,
                )
                for number in range(1, 6)
            ]
        )
        session.flush()

        for version, dataset_id in [(1, PREVIOUS_DATASET), (2, CURRENT_DATASET)]:
            run_id = UUID(int=100 + version)
            fetched_at = SOURCE_TIME - timedelta(days=2 - version)
            session.add(
                IngestionRun(
                    id=run_id,
                    started_at=fetched_at,
                    finished_at=fetched_at + timedelta(minutes=1),
                    status="succeeded",
                    input_hash=sha256(f"utscvacant:synthetic:v1:{version}".encode()).hexdigest(),
                    counts={"rooms": 5, "coverage": 4, "occurrences": 1 if version == 1 else 3},
                )
            )
            session.flush()
            dataset = Dataset(id=dataset_id, run_id=run_id, source_fetched_at=fetched_at)
            session.add(dataset)
            session.flush()
            for room_id, completeness in enumerate(
                ["complete", "complete", "partial", "unknown"], 1
            ):
                session.add(
                    RoomCoverage(
                        dataset_id=dataset_id,
                        room_id=room_id,
                        completeness=completeness,
                        starts_at=datetime(2026, 10, 14, 4, tzinfo=UTC),
                        ends_at=datetime(2026, 10, 15, 4, tzinfo=UTC),
                    )
                )
            for offset in range(1 if version == 1 else 3):
                session.add(
                    MeetingOccurrence(
                        id=1 if version == 1 else 2 + offset,
                        dataset_id=dataset_id,
                        room_id=1,
                        source_key=f"synthetic:event:{offset}",
                        starts_at=SOURCE_TIME + timedelta(hours=offset + 1),
                        ends_at=SOURCE_TIME + timedelta(hours=offset + 2),
                        status="cancelled" if offset == 2 else "scheduled",
                    )
                )
            session.flush()
            dataset.published_at = fetched_at + timedelta(minutes=2)
            session.add(dataset)
            session.flush()

        session.add(
            IngestionRun(
                id=UUID(int=103),
                started_at=SOURCE_TIME + timedelta(hours=1),
                finished_at=SOURCE_TIME + timedelta(hours=1, minutes=1),
                status="failed",
                input_hash=sha256(b"utscvacant:synthetic:v1:failed").hexdigest(),
                counts={},
                error_code="synthetic_failure",
            )
        )
        session.add(ActivePeriod(start_date=date(2026, 10, 14), end_date=date(2026, 10, 15),
                                 dataset_id=CURRENT_DATASET))
        state.active_dataset_id = CURRENT_DATASET
        session.add(state)
        session.flush()
        for table in ("buildings", "rooms", "meeting_occurrences"):
            session.execute(
                text(f"""
                SELECT setval(pg_get_serial_sequence('utscvacant.{table}', 'id'),
                    (SELECT max(id) FROM utscvacant.{table}))
            """)
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic", action="store_true", required=True)
    parser.parse_args()
    engine = None
    try:
        engine = create_db_engine("INGESTION_DATABASE_URL")
        seed_synthetic(engine)
    except ValueError as error:
        parser.exit(1, f"{error}\n")
    except SQLAlchemyError:
        parser.exit(
            1, "Database operation failed. Check connectivity, migrations, and permissions.\n"
        )
    finally:
        if engine is not None:
            engine.dispose()
    print("Synthetic seed ready. No live schedule source used.")


if __name__ == "__main__":
    main()
