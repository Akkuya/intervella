"""Independent active date ranges and source-day freshness; retain all history."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("room_coverage", sa.Column("source_date", sa.Date()), schema="utscvacant")
    op.create_table(
        "active_periods",
        sa.Column("start_date", sa.Date(), primary_key=True),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), sa.ForeignKey("utscvacant.datasets.id"),
                  nullable=False, unique=True),
        sa.CheckConstraint("end_date > start_date", name="ck_active_period_interval"),
        schema="utscvacant",
    )
    # Range GiST has native support; no extension or extra dependency is required.
    op.execute("""ALTER TABLE utscvacant.active_periods ADD CONSTRAINT active_periods_no_overlap
        EXCLUDE USING gist (daterange(start_date, end_date, '[)') WITH &&)""")
    op.create_table(
        "dataset_sources",
        sa.Column("dataset_id", sa.Uuid(), sa.ForeignKey("utscvacant.datasets.id"), primary_key=True),
        sa.Column("date", sa.Date(), primary_key=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        schema="utscvacant",
    )
    op.execute("""
        INSERT INTO utscvacant.dataset_sources (dataset_id, date, fetched_at)
        SELECT d.id, (s->>'date')::date, (s->>'fetched_at')::timestamptz
        FROM utscvacant.datasets d JOIN utscvacant.ingestion_runs r ON r.id=d.run_id
        CROSS JOIN LATERAL jsonb_array_elements(COALESCE(r.counts->'sources','[]')) s
    """)
    op.execute("""
        INSERT INTO utscvacant.active_periods (start_date, end_date, dataset_id)
        SELECT COALESCE((SELECT min(value::date) FROM jsonb_array_elements_text(r.counts->'dates')),
                        (min(c.starts_at) AT TIME ZONE 'America/Toronto')::date),
               COALESCE((SELECT max(value::date)+1 FROM jsonb_array_elements_text(r.counts->'dates')),
                        ((max(c.ends_at)-interval '1 microsecond') AT TIME ZONE 'America/Toronto')::date+1),
               d.id
        FROM utscvacant.dataset_state st JOIN utscvacant.datasets d ON d.id=st.active_dataset_id
        JOIN utscvacant.ingestion_runs r ON r.id=d.run_id
        JOIN utscvacant.room_coverage c ON c.dataset_id=d.id
        GROUP BY d.id,r.counts
    """)
    op.execute("""
        CREATE FUNCTION utscvacant.guard_active_period() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            PERFORM 1 FROM utscvacant.datasets
              WHERE id=NEW.dataset_id AND published_at IS NOT NULL FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'active dataset must be published' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""CREATE TRIGGER guard_active_period BEFORE INSERT OR UPDATE
        ON utscvacant.active_periods FOR EACH ROW EXECUTE FUNCTION utscvacant.guard_active_period()""")
    op.execute("""CREATE TRIGGER guard_source_payload BEFORE INSERT OR UPDATE OR DELETE
        ON utscvacant.dataset_sources FOR EACH ROW EXECUTE FUNCTION utscvacant.guard_payload()""")
    op.execute("REVOKE ALL ON utscvacant.active_periods, utscvacant.dataset_sources FROM PUBLIC")
    op.execute("REVOKE ALL ON FUNCTION utscvacant.guard_active_period() FROM PUBLIC")
    for table in ("active_periods", "dataset_sources"):
        op.execute(f"""CREATE TRIGGER reject_truncate BEFORE TRUNCATE ON utscvacant.{table}
            FOR EACH STATEMENT EXECUTE FUNCTION utscvacant.reject_removal()""")


def downgrade():
    # A single pointer cannot represent several periods. Refuse a lossy rollback.
    op.execute("""DO $$ BEGIN
        IF (SELECT count(*) FROM utscvacant.active_periods)>1 OR EXISTS (
            SELECT 1 FROM utscvacant.active_periods p, utscvacant.dataset_state s
            WHERE p.dataset_id IS DISTINCT FROM s.active_dataset_id
        ) THEN
            RAISE EXCEPTION 'retain one active period before downgrading';
        END IF;
    END $$""")
    op.drop_table("dataset_sources", schema="utscvacant")
    op.drop_column("room_coverage", "source_date", schema="utscvacant")
    op.drop_table("active_periods", schema="utscvacant")
    op.execute("DROP FUNCTION utscvacant.guard_active_period()")
