"""Explicit, environment-only PostgreSQL connections; importing this module does no I/O."""

import os
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import URL, Engine, make_url
from sqlalchemy.exc import ArgumentError
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
    return create_engine(
        database_url(variable),
        pool_size=5,
        max_overflow=0,
        pool_pre_ping=True,
        hide_parameters=True,
        echo=False,
        connect_args={
            "connect_timeout": 10,
            "options": "-c timezone=UTC -c statement_timeout=3000",
        },
    )


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_db_engine()


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
