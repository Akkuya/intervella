import subprocess
import sys

import pytest
from sqlalchemy import text
from sqlmodel import Session, select

from app import seed
from app.models import (
    Building,
    Dataset,
    DatasetState,
    IngestionRun,
    MeetingOccurrence,
    Room,
    RoomCoverage,
)

pytestmark = pytest.mark.postgres


def snapshot(engine):
    with Session(engine) as session:
        return {
            model.__tablename__: [
                record.model_dump() for record in session.exec(select(model)).all()
            ]
            for model in [
                Building,
                Room,
                IngestionRun,
                Dataset,
                DatasetState,
                RoomCoverage,
                MeetingOccurrence,
            ]
        }


def test_seed_is_repeatable_with_explicit_unknown_coverage(postgres_engine):
    seed.seed_synthetic(postgres_engine)
    first = snapshot(postgres_engine)
    seed.seed_synthetic(postgres_engine)
    assert snapshot(postgres_engine) == first
    assert len(first["buildings"]) == 2
    assert len(first["rooms"]) == 5
    assert len(first["datasets"]) == 2
    assert len(first["ingestion_runs"]) == 3
    assert any(
        run["status"] == "failed" and run["error_code"] == "synthetic_failure"
        for run in first["ingestion_runs"]
    )
    with Session(postgres_engine) as session:
        active = session.get(DatasetState, 1).active_dataset_id
        assert active == seed.CURRENT_DATASET
        coverage = session.exec(select(RoomCoverage).where(RoomCoverage.dataset_id == active)).all()
        assert {row.completeness for row in coverage} == {"complete", "partial", "unknown"}
        assert len(coverage) == 4
        assert any(row["status"] == "cancelled" for row in first["meeting_occurrences"])
        assert len({row.room_id for row in coverage}) == 4
    with postgres_engine.connect() as connection:
        assert (
            connection.scalar(
                text("""
            SELECT count(*) FROM utscvacant.rooms r
            LEFT JOIN utscvacant.room_coverage c ON c.room_id=r.id AND c.dataset_id=:id
            WHERE c.room_id IS NULL
        """),
                {"id": active},
            )
            == 1
        )


def test_seed_has_stable_room_identity_across_versions(postgres_engine):
    seed.seed_synthetic(postgres_engine)
    with postgres_engine.connect() as connection:
        assert (
            connection.scalar(
                text("""
            SELECT count(*) FROM (
                SELECT room_id FROM utscvacant.meeting_occurrences
                GROUP BY room_id HAVING count(DISTINCT dataset_id)=2
            ) shared
        """)
            )
            == 1
        )
    # Explicit synthetic IDs must not leave PostgreSQL identity sequences behind.
    with Session(postgres_engine) as session:
        building = Building(code="AFTER", name="After seed")
        session.add(building)
        session.flush()
        assert building.id > 2


def test_seed_refuses_unrelated_data(postgres_engine):
    with postgres_engine.begin() as connection:
        connection.execute(
            text("INSERT INTO utscvacant.buildings (code,name) VALUES ('EXISTING','Existing')")
        )
    before = snapshot(postgres_engine)
    with pytest.raises(ValueError, match="empty"):
        seed.seed_synthetic(postgres_engine)
    assert snapshot(postgres_engine) == before


def test_seed_cli_requires_explicit_synthetic_flag():
    result = subprocess.run([sys.executable, "-m", "app.seed"], capture_output=True, text=True)
    assert result.returncode == 2
    assert "--synthetic" in result.stderr
