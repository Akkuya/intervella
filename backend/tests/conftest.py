import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.db import database_url


def pytest_addoption(parser):
    parser.addoption(
        "--require-postgres", action="store_true", help="Fail if TEST_DATABASE_URL is unset"
    )


def pytest_configure(config):
    if config.getoption("--require-postgres") and not os.environ.get("TEST_DATABASE_URL"):
        raise pytest.UsageError("--require-postgres requires TEST_DATABASE_URL")


def migration_config(connection):
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


@pytest.fixture
def postgres_engine():
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.skip("Set TEST_DATABASE_URL to run real PostgreSQL integration tests")
    # Only this randomly named database is ever dropped; the supplied database is untouched.
    name = "utscvacant_test_" + uuid4().hex
    url = database_url("TEST_DATABASE_URL")
    admin = create_engine(url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    engine = create_engine(url.set(database=name), hide_parameters=True)
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        with engine.begin() as connection:
            command.upgrade(migration_config(connection), "head")
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def connection(postgres_engine):
    with postgres_engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()


@pytest.fixture
def authenticated_student(monkeypatch):
    """Schedule-only contracts authenticate explicitly; auth tests use the real boundary."""
    from app.student_auth.service import StudentAuth

    monkeypatch.setattr(StudentAuth, "require", lambda self, request: None)
