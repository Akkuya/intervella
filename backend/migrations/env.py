"""Alembic uses an explicit migration role; URLs never enter config files or logging."""

from alembic import context
from sqlmodel import SQLModel

from app import models  # noqa: F401
from app.db import create_db_engine, database_url


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name in {None, "utscvacant"}
    if type_ == "table":
        return parent_names.get("schema_name") == "utscvacant"
    return True


def configure(connection=None):
    options = dict(
        target_metadata=SQLModel.metadata,
        include_schemas=True,
        include_name=include_name,
        compare_type=True,
        compare_server_default=True,
    )
    if connection is None:
        context.configure(url=database_url("MIGRATION_DATABASE_URL"), literal_binds=True, **options)
    else:
        context.configure(connection=connection, **options)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    configure()
elif (connection := context.config.attributes.get("connection")) is not None:
    configure(connection)
else:
    engine = create_db_engine("MIGRATION_DATABASE_URL")
    try:
        with engine.connect() as connection:
            configure(connection)
    finally:
        engine.dispose()
