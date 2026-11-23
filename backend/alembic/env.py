from alembic import context
from alembic.script import ScriptDirectory
from sqlalchemy import engine_from_config, pool

from app.database import Base, DATABASE_URL
from app import models  # noqa: F401
from app.retirement import RETIREMENT_COMMAND, RETIREMENT_REVISION

config = context.config
config.set_main_option("sqlalchemy.url", DATABASE_URL)
target_metadata = Base.metadata


def targets_retirement() -> bool:
    target = context.get_revision_argument()
    if target is None:
        return False
    scripts = ScriptDirectory.from_config(config)
    return any(revision.revision == RETIREMENT_REVISION for revision in scripts.iterate_revisions(target, "base"))


def enable_foreign_keys(connection) -> None:
    if connection.connection.driver_connection.in_transaction:
        raise RuntimeError("Foreign keys must be enabled before the write transaction")
    connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    if connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 1:
        raise RuntimeError("SQLite foreign keys could not be enabled")


def inspect_cutover(connection) -> tuple[bool, tuple[str, ...]]:
    objects = connection.exec_driver_sql(
        "SELECT type, name FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*'"
    ).all()
    versions = tuple(connection.exec_driver_sql(
        "SELECT version_num FROM alembic_version"
    ).scalars()) if ("table", "alembic_version") in objects else ()
    return not objects, versions


def reject_retirement_stamp(**kwargs) -> None:
    if kwargs["step"].is_stamp:
        raise RuntimeError("Legacy retirement must run as an upgrade, not a revision stamp")


def run_migrations_offline() -> None:
    if targets_retirement():
        raise RuntimeError("Legacy module retirement requires an online SQLite connection")
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
        cutover = targets_retirement()
        if cutover and connection.dialect.name != "sqlite":
            raise RuntimeError("Legacy module retirement requires SQLite")
        # Set the connection pragma before Alembic starts its SQLite transaction.
        if cutover:
            enable_foreign_keys(connection)
            connection.commit()
        # SQLite's legacy driver otherwise commits between revisions and leaves DDL
        # outside transactions. Keep the entire requested upgrade and stamp atomic.
        context.configure(connection=connection, target_metadata=target_metadata,
                          transactional_ddl=connection.dialect.name == "sqlite",
                          on_version_apply=reject_retirement_stamp if cutover else None)
        with context.begin_transaction():
            if connection.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            if cutover:
                fresh, versions = inspect_cutover(connection)
                if not fresh and versions != (RETIREMENT_REVISION,):
                    if versions not in {("20261029_21",), ("20261030_22",)}:
                        raise RuntimeError("Unsupported database revision for legacy module retirement")
                    if context.get_x_argument(as_dictionary=True).get("retire_legacy_modules") != "1":
                        raise RuntimeError(f"Existing work database requires explicit cutover: {RETIREMENT_COMMAND}")
                context.config.attributes["retirement_path"] = "fresh" if fresh else "existing"
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
