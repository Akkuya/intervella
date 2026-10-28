"""create PostgreSQL schedule foundation"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE SCHEMA utscvacant")
    op.execute("REVOKE ALL ON SCHEMA utscvacant FROM PUBLIC")
    op.create_table(
        "buildings",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.CheckConstraint("btrim(code) <> '' AND btrim(name) <> ''", name="ck_buildings_labels"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_buildings_code"),
        schema="utscvacant",
    )
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), server_default="running", nullable=False),
        sa.Column("input_hash", sa.Text(), nullable=False),
        sa.Column(
            "counts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "(status = 'running' AND finished_at IS NULL) OR "
            "(status <> 'running' AND finished_at IS NOT NULL AND finished_at >= started_at)",
            name="ck_ingestion_runs_finished",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code ~ '^[a-z][a-z0-9_]{0,63}$'",
            name="ck_ingestion_runs_error_code",
        ),
        sa.CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name="ck_ingestion_runs_hash"),
        sa.CheckConstraint("jsonb_typeof(counts) = 'object'", name="ck_ingestion_runs_counts"),
        sa.CheckConstraint(
            "status IN ('running','succeeded','failed')", name="ck_ingestion_runs_status"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="utscvacant",
    )
    op.create_table(
        "datasets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.Text(), server_default="America/Toronto", nullable=False),
        sa.CheckConstraint("timezone = 'America/Toronto'", name="ck_datasets_timezone"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["utscvacant.ingestion_runs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="utscvacant",
    )
    op.create_table(
        "rooms",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("building_id", sa.BigInteger(), nullable=False),
        sa.Column("room_number", sa.Text(), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.CheckConstraint("btrim(room_number) <> ''", name="ck_rooms_number"),
        sa.CheckConstraint("capacity IS NULL OR capacity > 0", name="ck_rooms_capacity"),
        sa.ForeignKeyConstraint(
            ["building_id"],
            ["utscvacant.buildings.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("building_id", "room_number", name="uq_rooms_building_number"),
        schema="utscvacant",
    )
    op.create_table(
        "dataset_state",
        sa.Column("id", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("active_dataset_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_dataset_state_singleton"),
        sa.ForeignKeyConstraint(
            ["active_dataset_id"],
            ["utscvacant.datasets.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="utscvacant",
    )
    op.create_table(
        "meeting_occurrences",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("room_id", sa.BigInteger(), nullable=False),
        sa.Column("source_key", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.CheckConstraint("btrim(source_key) <> ''", name="ck_meeting_occurrences_source_key"),
        sa.CheckConstraint(
            "status IN ('scheduled','cancelled')", name="ck_meeting_occurrences_status"
        ),
        sa.CheckConstraint("ends_at > starts_at", name="ck_meeting_occurrences_interval"),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["utscvacant.datasets.id"],
        ),
        sa.ForeignKeyConstraint(
            ["room_id"],
            ["utscvacant.rooms.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_id", "source_key", name="uq_meeting_occurrences_source"),
        schema="utscvacant",
    )
    op.create_index(
        "ix_meeting_occurrences_dataset_room_start",
        "meeting_occurrences",
        ["dataset_id", "room_id", "starts_at"],
        unique=False,
        schema="utscvacant",
    )
    op.create_table(
        "room_coverage",
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("room_id", sa.BigInteger(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completeness", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "completeness IN ('complete','partial','unknown')", name="ck_room_coverage_completeness"
        ),
        sa.CheckConstraint("ends_at > starts_at", name="ck_room_coverage_interval"),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["utscvacant.datasets.id"],
        ),
        sa.ForeignKeyConstraint(
            ["room_id"],
            ["utscvacant.rooms.id"],
        ),
        sa.PrimaryKeyConstraint("dataset_id", "room_id"),
        schema="utscvacant",
    )
    op.execute("INSERT INTO utscvacant.dataset_state (id) VALUES (1)")
    op.execute("""
        CREATE FUNCTION utscvacant.guard_dataset() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF TG_OP <> 'INSERT' AND OLD.published_at IS NOT NULL THEN
                RAISE EXCEPTION 'published dataset is immutable' USING ERRCODE = '23514';
            END IF;
            IF TG_OP <> 'DELETE' AND NEW.published_at IS NOT NULL THEN
                PERFORM 1 FROM utscvacant.ingestion_runs
                    WHERE id = NEW.run_id AND status = 'succeeded' FOR SHARE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'publication requires successful validation run'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER guard_dataset BEFORE INSERT OR UPDATE OR DELETE ON utscvacant.datasets
        FOR EACH ROW EXECUTE FUNCTION utscvacant.guard_dataset()
    """)
    op.execute("""
        CREATE FUNCTION utscvacant.guard_payload() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE
            old_id uuid;
            new_id uuid;
            dataset record;
        BEGIN
            IF TG_OP <> 'INSERT' THEN old_id := OLD.dataset_id; END IF;
            IF TG_OP <> 'DELETE' THEN new_id := NEW.dataset_id; END IF;
            -- Parent locks serialize payload writes against publication, including row moves.
            FOR dataset IN SELECT published_at FROM utscvacant.datasets
                WHERE id IN (old_id, new_id) ORDER BY id FOR UPDATE
            LOOP
                IF dataset.published_at IS NOT NULL THEN
                    RAISE EXCEPTION 'published dataset payload is immutable'
                        USING ERRCODE = '23514';
                END IF;
            END LOOP;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END $$
    """)
    for table in ("meeting_occurrences", "room_coverage"):
        op.execute(f"""
            CREATE TRIGGER guard_payload BEFORE INSERT OR UPDATE OR DELETE ON utscvacant.{table}
            FOR EACH ROW EXECUTE FUNCTION utscvacant.guard_payload()
        """)
    op.execute("""
        CREATE FUNCTION utscvacant.guard_pointer() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF NEW.active_dataset_id IS NOT NULL THEN
                PERFORM 1 FROM utscvacant.datasets
                    WHERE id = NEW.active_dataset_id AND published_at IS NOT NULL FOR SHARE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'active dataset must be published' USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER guard_pointer BEFORE INSERT OR UPDATE ON utscvacant.dataset_state
        FOR EACH ROW EXECUTE FUNCTION utscvacant.guard_pointer()
    """)
    op.execute("""
        CREATE FUNCTION utscvacant.reject_removal() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            RAISE EXCEPTION 'protected schedule state cannot be removed'
                USING ERRCODE = '23514';
        END $$
    """)
    op.execute("""
        CREATE TRIGGER keep_singleton BEFORE DELETE ON utscvacant.dataset_state
        FOR EACH ROW EXECUTE FUNCTION utscvacant.reject_removal()
    """)
    for table in ("dataset_state", "meeting_occurrences", "room_coverage"):
        op.execute(f"""
            CREATE TRIGGER reject_truncate BEFORE TRUNCATE ON utscvacant.{table}
            FOR EACH STATEMENT EXECUTE FUNCTION utscvacant.reject_removal()
        """)
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA utscvacant FROM PUBLIC")
    op.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA utscvacant FROM PUBLIC")
    op.execute("REVOKE ALL ON ALL FUNCTIONS IN SCHEMA utscvacant FROM PUBLIC")


def downgrade():
    op.drop_table("room_coverage", schema="utscvacant")
    op.drop_index(
        "ix_meeting_occurrences_dataset_room_start",
        table_name="meeting_occurrences",
        schema="utscvacant",
    )
    op.drop_table("meeting_occurrences", schema="utscvacant")
    op.drop_table("dataset_state", schema="utscvacant")
    op.drop_table("rooms", schema="utscvacant")
    op.drop_table("datasets", schema="utscvacant")
    op.drop_table("ingestion_runs", schema="utscvacant")
    op.drop_table("buildings", schema="utscvacant")
    for function in ("guard_dataset", "guard_payload", "guard_pointer", "reject_removal"):
        op.execute(f"DROP FUNCTION utscvacant.{function}()")
    op.execute("DROP SCHEMA utscvacant")
