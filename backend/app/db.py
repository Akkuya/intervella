"""Explicit, environment-only PostgreSQL connections; importing this module does no I/O."""

import os
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import URL, Engine, event, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.pool import NullPool
from sqlmodel import Session, create_engine


def database_url(variable: str = "DATABASE_URL") -> URL:
    value = os.environ.get(variable)
    if not value:
        raise ValueError(f"{variable} is required")
    try:
        url = make_url(value)
        if url.drivername not in {"postgresql", "postgresql+psycopg"} or not url.database:
            raise ValueError
        return url.set(drivername="postgresql+psycopg")
    except (ArgumentError, ValueError):
        raise ValueError(f"{variable} must be a PostgreSQL URL using Psycopg 3") from None


def create_db_engine(variable: str = "DATABASE_URL") -> Engine:
    mode = os.getenv("DATABASE_POOL_MODE", "session")
    if mode not in {"session", "transaction"}:
        raise ValueError("DATABASE_POOL_MODE must be session or transaction")
    pooled = mode == "transaction"
    engine = create_engine(
        database_url(variable),
        **({"poolclass": NullPool} if pooled else {"pool_size": 5, "max_overflow": 0}),
        pool_pre_ping=True,
        hide_parameters=True,
        echo=False,
        connect_args=(
            {"connect_timeout": 5, "prepare_threshold": None}
            if pooled
            else {
                "connect_timeout": 10,
                "options": "-c timezone=UTC -c statement_timeout=3000",
            }
        ),
    )
    if pooled:

        @event.listens_for(engine, "begin")
        def local_settings(connection):
            # Pooler backends change after each transaction; never leave session-level state.
            if not connection.connection.dbapi_connection.autocommit:
                connection.exec_driver_sql("SET LOCAL timezone = 'UTC'")
                connection.exec_driver_sql("SET LOCAL statement_timeout = '3s'")

    return engine


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_db_engine()


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


def get_read_session() -> Iterator[Session]:
    """One read-only MVCC snapshot per request, including room metadata and freshness."""
    from app.errors import APIError

    try:
        engine = get_engine()
    except ValueError:
        raise APIError(503, "database_unavailable", "Schedule database is unavailable.") from None
    with (
        engine.connect().execution_options(
            isolation_level="REPEATABLE READ", postgresql_readonly=True
        ) as connection,
        Session(connection) as session,
    ):
        yield session
