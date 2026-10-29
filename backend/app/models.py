"""Stable room identities and dataset-scoped schedule records (TRD v1.0)."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Identity,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class Building(SQLModel, table=True):
    __tablename__ = "buildings"
    __table_args__ = (
        UniqueConstraint("code", name="uq_buildings_code"),
        CheckConstraint("btrim(code) <> '' AND btrim(name) <> ''", name="ck_buildings_labels"),
        {"schema": "utscvacant"},
    )
    id: int | None = Field(default=None, sa_column=Column(BigInteger, Identity(), primary_key=True))
    code: str = Field(sa_type=Text)
    name: str = Field(sa_type=Text)


class Room(SQLModel, table=True):
    __tablename__ = "rooms"
    __table_args__ = (
        UniqueConstraint("building_id", "room_number", name="uq_rooms_building_number"),
        CheckConstraint("btrim(room_number) <> ''", name="ck_rooms_number"),
        CheckConstraint("capacity IS NULL OR capacity > 0", name="ck_rooms_capacity"),
        {"schema": "utscvacant"},
    )
    id: int | None = Field(default=None, sa_column=Column(BigInteger, Identity(), primary_key=True))
    building_id: int = Field(sa_type=BigInteger, foreign_key="utscvacant.buildings.id")
    room_number: str = Field(sa_type=Text)
    capacity: int | None = None
    active: bool = Field(default=True, sa_column_kwargs={"server_default": text("true")})


class IngestionRun(SQLModel, table=True):
    __tablename__ = "ingestion_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running','succeeded','failed')", name="ck_ingestion_runs_status"
        ),
        CheckConstraint(
            "(status = 'running' AND finished_at IS NULL) OR "
            "(status <> 'running' AND finished_at IS NOT NULL AND finished_at >= started_at)",
            name="ck_ingestion_runs_finished",
        ),
        CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name="ck_ingestion_runs_hash"),
        CheckConstraint("jsonb_typeof(counts) = 'object'", name="ck_ingestion_runs_counts"),
        CheckConstraint(
            "error_code IS NULL OR error_code ~ '^[a-z][a-z0-9_]{0,63}$'",
            name="ck_ingestion_runs_error_code",
        ),
        {"schema": "utscvacant"},
    )
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    started_at: datetime = Field(sa_type=DateTime(timezone=True))
    finished_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    status: str = Field(
        default="running", sa_type=Text, sa_column_kwargs={"server_default": "running"}
    )
    input_hash: str = Field(sa_type=Text)
    counts: dict = Field(
        default_factory=dict,
        sa_type=JSONB,
        sa_column_kwargs={"server_default": text("'{}'::jsonb")},
    )
    error_code: str | None = Field(default=None, sa_type=Text)


class Dataset(SQLModel, table=True):
    __tablename__ = "datasets"
    __table_args__ = (
        CheckConstraint("timezone = 'America/Toronto'", name="ck_datasets_timezone"),
        {"schema": "utscvacant"},
    )
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    run_id: UUID = Field(foreign_key="utscvacant.ingestion_runs.id")
    published_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    source_fetched_at: datetime = Field(sa_type=DateTime(timezone=True))
    timezone: str = Field(
        default="America/Toronto",
        sa_type=Text,
        sa_column_kwargs={"server_default": "America/Toronto"},
    )


class DatasetState(SQLModel, table=True):
    __tablename__ = "dataset_state"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_dataset_state_singleton"),
        {"schema": "utscvacant"},
    )
    id: int = Field(
        default=1, sa_column=Column(SmallInteger, primary_key=True, autoincrement=False)
    )
    active_dataset_id: UUID | None = Field(default=None, foreign_key="utscvacant.datasets.id")


class RoomCoverage(SQLModel, table=True):
    __tablename__ = "room_coverage"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_room_coverage_interval"),
        CheckConstraint(
            "completeness IN ('complete','partial','unknown')", name="ck_room_coverage_completeness"
        ),
        {"schema": "utscvacant"},
    )
    dataset_id: UUID = Field(primary_key=True, foreign_key="utscvacant.datasets.id")
    room_id: int = Field(primary_key=True, sa_type=BigInteger, foreign_key="utscvacant.rooms.id")
    starts_at: datetime = Field(primary_key=True, sa_type=DateTime(timezone=True))
    ends_at: datetime = Field(sa_type=DateTime(timezone=True))
    completeness: str = Field(sa_type=Text)


class MeetingOccurrence(SQLModel, table=True):
    __tablename__ = "meeting_occurrences"
    __table_args__ = (
        UniqueConstraint("dataset_id", "source_key", name="uq_meeting_occurrences_source"),
        CheckConstraint("ends_at > starts_at", name="ck_meeting_occurrences_interval"),
        CheckConstraint(
            "status IN ('scheduled','cancelled')", name="ck_meeting_occurrences_status"
        ),
        CheckConstraint("btrim(source_key) <> ''", name="ck_meeting_occurrences_source_key"),
        Index("ix_meeting_occurrences_dataset_room_start", "dataset_id", "room_id", "starts_at"),
        {"schema": "utscvacant"},
    )
    id: int | None = Field(default=None, sa_column=Column(BigInteger, Identity(), primary_key=True))
    dataset_id: UUID = Field(foreign_key="utscvacant.datasets.id")
    room_id: int = Field(sa_type=BigInteger, foreign_key="utscvacant.rooms.id")
    source_key: str = Field(sa_type=Text)
    starts_at: datetime = Field(sa_type=DateTime(timezone=True))
    ends_at: datetime = Field(sa_type=DateTime(timezone=True))
    status: str = Field(sa_type=Text)
