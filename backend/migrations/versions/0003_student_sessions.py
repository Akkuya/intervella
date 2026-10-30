"""Isolated student authentication store; timetable tables are unchanged."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE SCHEMA student_auth")
    op.create_table(
        "session",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("policy", sa.String(64), nullable=False),
        sa.Column("csrf", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("subject", sa.String(256), nullable=False),
        sa.Column("access_expires_at", sa.DateTime(timezone=True)),
        sa.Column("provider_tokens", sa.Text()),
        schema="student_auth",
    )
    op.create_index(
        "ix_student_auth_session_expires_at", "session", ["expires_at"], schema="student_auth"
    )
    op.create_table(
        "attempt",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("window", sa.Integer(), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False),
        schema="student_auth",
    )
    op.create_table(
        "control",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("policy", sa.String(64), nullable=False),
        sa.CheckConstraint("id = 1", name="student_auth_control_singleton"),
        schema="student_auth",
    )
    op.execute("INSERT INTO student_auth.control (id,policy) VALUES (1,'')")


def downgrade():
    op.drop_table("control", schema="student_auth")
    op.drop_table("attempt", schema="student_auth")
    op.drop_index("ix_student_auth_session_expires_at", table_name="session", schema="student_auth")
    op.drop_table("session", schema="student_auth")
    op.execute("DROP SCHEMA student_auth")
