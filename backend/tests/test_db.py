import pytest

from app import db


def test_required_url_does_not_fall_back(monkeypatch):
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://localhost/other")
    with pytest.raises(ValueError, match="MIGRATION_DATABASE_URL is required"):
        db.database_url("MIGRATION_DATABASE_URL")


@pytest.mark.parametrize(
    "value", ["", "sqlite:///data.db", "postgresql+psycopg2://host/db", "bad://secret@"]
)
def test_rejects_unsupported_urls_without_secrets(monkeypatch, value):
    monkeypatch.setenv("DATABASE_URL", value)
    with pytest.raises(ValueError) as error:
        db.database_url()
    assert "secret" not in str(error.value)


def test_postgresql_url_uses_psycopg(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@localhost/example")
    url = db.database_url()
    assert url.drivername == "postgresql+psycopg"
    assert url.password == "secret"


def test_engine_has_bounded_pool_and_no_sql_logging(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://localhost/example")
    engine = db.create_db_engine()
    try:
        assert engine.pool.size() == 5
        assert engine.pool._max_overflow == 0
        assert engine.echo is False
        assert engine.hide_parameters is True
    finally:
        engine.dispose()


def test_transaction_pooler_disables_local_pool_prepares_and_startup_options(monkeypatch):
    from sqlalchemy.pool import NullPool

    monkeypatch.setenv("DATABASE_URL", "postgresql://reader:secret@host/example?sslmode=require")
    monkeypatch.setenv("DATABASE_POOL_MODE", "transaction")
    original = db.create_engine
    settings = {}

    def capture(url, **kwargs):
        settings.update(kwargs)
        return original(url, **kwargs)

    monkeypatch.setattr(db, "create_engine", capture)
    engine = db.create_db_engine()
    try:
        assert isinstance(engine.pool, NullPool)
        assert settings["connect_args"]["prepare_threshold"] is None
        assert "options" not in settings["connect_args"]
        assert settings["connect_args"]["connect_timeout"] == 5
        assert engine.hide_parameters and not engine.echo
    finally:
        engine.dispose()


def test_unknown_pool_mode_is_rejected(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://host/example")
    monkeypatch.setenv("DATABASE_POOL_MODE", "unknown")
    with pytest.raises(ValueError, match="DATABASE_POOL_MODE"):
        db.create_db_engine()
