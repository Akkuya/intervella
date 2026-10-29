"""Allow multiple coverage windows without rewriting existing data.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("room_coverage_pkey", "room_coverage", schema="utscvacant", type_="primary")
    op.create_primary_key(
        "room_coverage_pkey",
        "room_coverage",
        ["dataset_id", "room_id", "starts_at"],
        schema="utscvacant",
    )


def downgrade():
    # Refuse a lossy downgrade; leave all windows and the migration version intact.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM utscvacant.room_coverage
                       GROUP BY dataset_id, room_id HAVING count(*) > 1) THEN
                RAISE EXCEPTION 'multiple coverage windows require forward repair, not downgrade';
            END IF;
        END $$
    """)
    op.drop_constraint("room_coverage_pkey", "room_coverage", schema="utscvacant", type_="primary")
    op.create_primary_key(
        "room_coverage_pkey", "room_coverage", ["dataset_id", "room_id"], schema="utscvacant"
    )
