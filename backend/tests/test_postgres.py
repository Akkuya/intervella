from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event
from uuid import UUID

import pytest
from alembic import command
from conftest import migration_config
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlmodel import Session

pytestmark = pytest.mark.postgres
RUN = "00000000-0000-0000-0000-000000000001"
DATASET = "00000000-0000-0000-0000-000000000002"
OTHER = "00000000-0000-0000-0000-000000000003"


@pytest.fixture
def candidate(connection):
    connection.execute(
        text("INSERT INTO utscvacant.buildings (id,code,name) VALUES (1,'SYN','Synthetic')")
    )
    connection.execute(
        text("INSERT INTO utscvacant.rooms (id,building_id,room_number) VALUES (1,1,'101')")
    )
    connection.execute(
        text("""
        INSERT INTO utscvacant.ingestion_runs (id,started_at,status,input_hash)
        VALUES (:id,'2026-10-14T12:00:00Z','running',:hash)
    """),
        {"id": RUN, "hash": "a" * 64},
    )
    for dataset in [DATASET, OTHER]:
        connection.execute(
            text("""
            INSERT INTO utscvacant.datasets (id,run_id,source_fetched_at)
            VALUES (:id,:run,'2026-10-14T12:00:00Z')
        """),
            {"id": dataset, "run": RUN},
        )
    return connection


def occurrence(connection, dataset=DATASET, key="event", status="scheduled"):
    connection.execute(
        text("""
        INSERT INTO utscvacant.meeting_occurrences
            (dataset_id,room_id,source_key,starts_at,ends_at,status)
        VALUES (:dataset,1,:key,'2026-10-14T09:00:00-04:00','2026-10-14T10:00:00-04:00',:status)
    """),
        {"dataset": dataset, "key": key, "status": status},
    )


def publish(connection):
    connection.execute(
        text("""
        UPDATE utscvacant.ingestion_runs SET status='succeeded',finished_at='2026-10-14T12:01:00Z'
        WHERE id=:id
    """),
        {"id": RUN},
    )
    connection.execute(
        text("UPDATE utscvacant.datasets SET published_at='2026-10-14T12:02:00Z' WHERE id=:id"),
        {"id": DATASET},
    )
    connection.execute(
        text("UPDATE utscvacant.dataset_state SET active_dataset_id=:id WHERE id=1"),
        {"id": DATASET},
    )


def test_empty_migration_and_model_metadata(connection):
    assert connection.execute(
        text("SELECT id,active_dataset_id FROM utscvacant.dataset_state")
    ).all() == [(1, None)]
    assert set(inspect(connection).get_table_names(schema="utscvacant")) == {
        "buildings",
        "rooms",
        "ingestion_runs",
        "datasets",
        "dataset_state",
        "room_coverage",
        "meeting_occurrences",
    }
    command.check(migration_config(connection))


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO utscvacant.buildings (code,name) VALUES ('  ','name')",
        "INSERT INTO utscvacant.buildings (code,name) VALUES ('other','')",
        "INSERT INTO utscvacant.buildings (code,name) VALUES ('SYN','duplicate')",
        "INSERT INTO utscvacant.rooms (building_id,room_number) VALUES (999,'101')",
        "INSERT INTO utscvacant.rooms (building_id,room_number) VALUES (1,'101')",
        "INSERT INTO utscvacant.rooms (building_id,room_number,capacity) VALUES (1,'102',0)",
        "INSERT INTO utscvacant.rooms (building_id,room_number) VALUES (1,' ')",
        "UPDATE utscvacant.ingestion_runs SET status='invalid'",
        "UPDATE utscvacant.ingestion_runs SET status='failed'",
        "UPDATE utscvacant.ingestion_runs SET counts='[]'::jsonb",
        "UPDATE utscvacant.ingestion_runs SET input_hash=' ' ",
        "UPDATE utscvacant.ingestion_runs SET finished_at='2020-01-01Z'",
        "UPDATE utscvacant.datasets SET run_id='00000000-0000-0000-0000-000000000099'",
        "DELETE FROM utscvacant.rooms WHERE id=1",
    ],
)
def test_constraints_reject_invalid_data(candidate, statement):
    # A referencing coverage row also proves that room deletion is restrictive.
    candidate.execute(
        text("""
        INSERT INTO utscvacant.room_coverage VALUES
            (:dataset,1,'2026-10-14T00:00:00Z','2026-10-15T00:00:00Z','unknown')
    """),
        {"dataset": DATASET},
    )
    with pytest.raises(IntegrityError), candidate.begin_nested():
        candidate.execute(text(statement))


@pytest.mark.parametrize(
    "table,changes",
    [
        ("meeting_occurrences", "ends_at=starts_at"),
        ("meeting_occurrences", "ends_at=starts_at - interval '1 minute'"),
        ("meeting_occurrences", "status='unknown'"),
        ("meeting_occurrences", "source_key=' '"),
        ("meeting_occurrences", "room_id=999"),
        ("room_coverage", "ends_at=starts_at"),
        ("room_coverage", "completeness='available'"),
    ],
)
def test_occurrence_and_coverage_constraints(candidate, table, changes):
    occurrence(candidate)
    candidate.execute(
        text("""
        INSERT INTO utscvacant.room_coverage VALUES
            (:dataset,1,'2026-10-14T00:00:00Z','2026-10-15T00:00:00Z','complete')
    """),
        {"dataset": DATASET},
    )
    with pytest.raises(IntegrityError), candidate.begin_nested():
        candidate.execute(text(f"UPDATE utscvacant.{table} SET {changes}"))


def test_dataset_isolation_duplicates_and_timezone(candidate):
    occurrence(candidate)
    occurrence(candidate, OTHER, status="cancelled")
    with pytest.raises(IntegrityError), candidate.begin_nested():
        occurrence(candidate)
    rows = candidate.execute(
        text(
            "SELECT dataset_id,starts_at,status FROM utscvacant.meeting_occurrences "
            "ORDER BY dataset_id"
        )
    ).all()
    assert rows == [
        (UUID(DATASET), datetime(2026, 10, 14, 13, tzinfo=UTC), "scheduled"),
        (UUID(OTHER), datetime(2026, 10, 14, 13, tzinfo=UTC), "cancelled"),
    ]
    assert candidate.scalar(text("SELECT count(*) FROM utscvacant.room_coverage")) == 0


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM utscvacant.dataset_state",
        "TRUNCATE utscvacant.dataset_state",
        "UPDATE utscvacant.dataset_state SET id=2",
        "INSERT INTO utscvacant.dataset_state (id) VALUES (2)",
        f"UPDATE utscvacant.dataset_state SET active_dataset_id='{DATASET}'",
        f"UPDATE utscvacant.datasets SET published_at=now() WHERE id='{DATASET}'",
    ],
)
def test_publication_prerequisites_and_singleton(candidate, statement):
    with pytest.raises(DBAPIError), candidate.begin_nested():
        candidate.execute(text(statement))


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE utscvacant.meeting_occurrences SET status='cancelled'",
        "DELETE FROM utscvacant.meeting_occurrences",
        "TRUNCATE utscvacant.meeting_occurrences",
        f"UPDATE utscvacant.meeting_occurrences SET dataset_id='{OTHER}'",
        "UPDATE utscvacant.room_coverage SET completeness='unknown'",
        "DELETE FROM utscvacant.room_coverage",
        f"UPDATE utscvacant.datasets SET published_at=NULL WHERE id='{DATASET}'",
        f"UPDATE utscvacant.datasets SET source_fetched_at=now() WHERE id='{DATASET}'",
    ],
)
def test_published_payload_is_immutable(candidate, statement):
    occurrence(candidate)
    candidate.execute(
        text("""
        INSERT INTO utscvacant.room_coverage VALUES
            (:dataset,1,'2026-10-14T00:00:00Z','2026-10-15T00:00:00Z','complete')
    """),
        {"dataset": DATASET},
    )
    publish(candidate)
    with pytest.raises(DBAPIError), candidate.begin_nested():
        candidate.execute(text(statement))
    with pytest.raises(DBAPIError), candidate.begin_nested():
        occurrence(candidate, key="extra")


def test_failed_publication_rolls_back_pointer(candidate):
    publish(candidate)
    with pytest.raises(DBAPIError), candidate.begin_nested():
        candidate.execute(
            text("UPDATE utscvacant.dataset_state SET active_dataset_id=:id"), {"id": OTHER}
        )
    assert candidate.scalar(text("SELECT active_dataset_id FROM utscvacant.dataset_state")) == UUID(
        DATASET
    )


def test_sqlmodel_roundtrip(connection):
    from app.models import Building, Room

    with Session(connection) as session:
        building = Building(code="ORM", name="ORM synthetic")
        session.add(building)
        session.flush()
        room = Room(building_id=building.id, room_number="201", capacity=None)
        session.add(room)
        session.flush()
        assert room.id > 0
        assert room.active is True


def test_migration_roundtrip(connection):
    config = migration_config(connection)
    command.downgrade(config, "base")
    assert not inspect(connection).has_schema("utscvacant")
    command.upgrade(config, "head")
    command.check(config)


def test_index_types_and_private_schema(connection):
    inspector = inspect(connection)
    indexes = inspector.get_indexes("meeting_occurrences", schema="utscvacant")
    assert any(index["column_names"] == ["dataset_id", "room_id", "starts_at"] for index in indexes)
    columns = {
        column["name"]: column
        for column in inspector.get_columns("meeting_occurrences", schema="utscvacant")
    }
    assert columns["starts_at"]["type"].timezone is True
    assert columns["id"]["identity"] is not None
    assert (
        connection.scalar(
            text("""
        SELECT count(*) FROM pg_namespace n,
            LATERAL aclexplode(coalesce(n.nspacl, acldefault('n', n.nspowner))) a
        WHERE n.nspname='utscvacant' AND a.grantee=0 AND a.privilege_type='USAGE'
    """)
        )
        == 0
    )


def test_session_dependency_rolls_back_uncommitted_work(postgres_engine, monkeypatch):
    from app import db
    from app.models import Building

    monkeypatch.setattr(db, "get_engine", lambda: postgres_engine)
    dependency = db.get_session()
    session = next(dependency)
    session.add(Building(code="ROLLBACK", name="Synthetic session"))
    session.flush()
    dependency.close()
    with postgres_engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM utscvacant.buildings WHERE code='ROLLBACK'")
            )
            == 0
        )


def test_payload_write_waits_for_publication(postgres_engine):
    # Commit fixtures so two independent connections can observe the same candidate.
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO utscvacant.buildings (id,code,name) "
                "VALUES (900,'RACE','Synthetic race')"
            )
        )
        connection.execute(
            text("INSERT INTO utscvacant.rooms (id,building_id,room_number) VALUES (900,900,'1')")
        )
        connection.execute(
            text("""
            INSERT INTO utscvacant.ingestion_runs (id,started_at,finished_at,status,input_hash)
            VALUES (:run,'2026-10-14T12:00:00Z','2026-10-14T12:01:00Z','succeeded',:hash)
        """),
            {"run": RUN, "hash": "b" * 64},
        )
        connection.execute(
            text("""
            INSERT INTO utscvacant.datasets (id,run_id,source_fetched_at)
            VALUES (:dataset,:run,'2026-10-14T12:00:00Z')
        """),
            {"dataset": DATASET, "run": RUN},
        )
    started = Event()

    def late_insert():
        with postgres_engine.begin() as connection:
            connection.execute(text("SET LOCAL statement_timeout='5s'"))
            started.set()
            connection.execute(
                text("""
                INSERT INTO utscvacant.meeting_occurrences
                (dataset_id,room_id,source_key,starts_at,ends_at,status)
                VALUES
                    (:dataset,900,'late','2026-10-14T13:00:00Z','2026-10-14T14:00:00Z','scheduled')
            """),
                {"dataset": DATASET},
            )

    # Roll back committed fixtures by database teardown, not by weakening immutable guards.
    with ThreadPoolExecutor(max_workers=1) as executor:
        with postgres_engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE utscvacant.datasets SET published_at='2026-10-14T12:02:00Z' "
                    "WHERE id=:id"
                ),
                {"id": DATASET},
            )
            future = executor.submit(late_insert)
            assert started.wait(3)
            assert not future.done()
        with pytest.raises(IntegrityError, match="immutable"):
            future.result(timeout=6)
