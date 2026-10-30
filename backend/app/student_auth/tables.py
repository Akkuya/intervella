"""Authentication-only tables, isolated from the immutable timetable datasets."""

from sqlalchemy import CheckConstraint, Column, DateTime, Integer, MetaData, String, Table, Text

metadata = MetaData(schema="student_auth")
sessions = Table(
    "session",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("policy", String(64), nullable=False),
    Column("csrf", String(64), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False, index=True),
    Column("subject", String(256), nullable=False),
    Column("access_expires_at", DateTime(timezone=True)),
    Column("provider_tokens", Text),
)
attempts = Table(
    "attempt",
    metadata,
    Column("key", String(64), primary_key=True),
    Column("window", Integer, primary_key=True),
    Column("count", Integer, nullable=False),
)

control = Table(
    "control",
    metadata,
    CheckConstraint("id = 1", name="student_auth_control_singleton"),
    Column("id", Integer, primary_key=True),
    Column("policy", String(64), nullable=False),
)
