"""Shared database revision check for the legacy module cutover."""

from sqlalchemy.engine import Engine

RETIREMENT_REVISION = "20261123_23"
RETIREMENT_COMMAND = "alembic -x retire_legacy_modules=1 upgrade head"


def require_current_schema(engine: Engine) -> None:
    with engine.connect() as connection:
        version_table = connection.exec_driver_sql(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='alembic_version'"
        ).scalar()
        versions = connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalars().all() if version_table else []
    if versions != [RETIREMENT_REVISION]:
        raise RuntimeError(
            "Database is not ready. Initialize an empty database with Alembic, "
            "or follow the explicit legacy module cutover procedure."
        )
