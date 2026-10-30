import pytest
from sqlalchemy import text

from app import db

pytestmark = pytest.mark.postgres


def test_transaction_pooler_uses_local_settings_and_readonly_snapshot(postgres_engine, monkeypatch):
    monkeypatch.setenv("DATABASE_POOL_MODE", "transaction")
    monkeypatch.setenv("DATABASE_URL", postgres_engine.url.render_as_string(hide_password=False))
    engine = db.create_db_engine()
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    try:
        for _ in range(2):
            generator = db.get_read_session()
            session = next(generator)
            assert session.scalar(text("SHOW timezone")) == "UTC"
            assert session.scalar(text("SHOW statement_timeout")) == "3s"
            assert session.scalar(text("SHOW transaction_isolation")) == "repeatable read"
            assert session.scalar(text("SHOW transaction_read_only")) == "on"
            generator.close()
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            assert conn.scalar(text("SHOW statement_timeout")) == "0"
    finally:
        engine.dispose()
