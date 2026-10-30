from alembic import context
from sqlalchemy import engine_from_config, pool

from app.database import Base, DATABASE_URL
from app import models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", DATABASE_URL)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=DATABASE_URL, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # SQLite's legacy driver otherwise commits between revisions and leaves DDL
        # outside transactions. Keep the entire requested upgrade and stamp atomic.
        context.configure(connection=connection, target_metadata=target_metadata,
                          transactional_ddl=connection.dialect.name == "sqlite")
        with context.begin_transaction():
            if connection.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
