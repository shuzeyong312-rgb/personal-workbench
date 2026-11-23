"""Remove the retired product library, quotation and customer reach schema."""

from alembic import op
from sqlalchemy import inspect

from app.retirement import RETIREMENT_REVISION

revision = RETIREMENT_REVISION
down_revision = "20261030_22"
branch_labels = None
depends_on = None

TABLES = (
    "library_simple_quote_evidence",
    "library_simple_eligibility_audit",
    "library_simple_source_events",
    "library_simple_product_events",
    "library_simple_quote_versions",
    "library_simple_quote_keys",
    "library_simple_sources",
    "library_product_prices",
    "library_product_variants",
    "library_product_sources",
    "library_imports",
    "library_products_legacy",
    "library_products",
    "library_products_history_snapshot",
    "library_product_variants_history_snapshot",
    "library_product_sources_history_snapshot",
    "library_product_prices_history_snapshot",
    "library_imports_history_snapshot",
    "library_history_manifest",
    "customer_reach_campaigns",
    "customer_reach_tasks",
)


def upgrade() -> None:
    migration = op.get_context()
    bind = op.get_bind()
    driver = bind.connection.driver_connection
    path = migration.config.attributes.get("retirement_path")
    if path not in {"fresh", "existing"}:
        raise RuntimeError("Legacy retirement requires a validated Alembic upgrade")
    if path == "fresh":
        # Historical SQLite revisions have their own commit boundaries.
        with migration.autocommit_block():
            bind.exec_driver_sql("PRAGMA foreign_keys=ON")
            if bind.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 1:
                raise RuntimeError("SQLite foreign keys could not be enabled")
        bind.exec_driver_sql("BEGIN IMMEDIATE")

    if not driver.in_transaction or bind.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 1:
        raise RuntimeError("Legacy retirement requires a write transaction with foreign keys enabled")

    if bind.exec_driver_sql("SELECT version_num FROM alembic_version").scalars().all() != [down_revision]:
        raise RuntimeError("Unexpected database revision before legacy retirement")

    schema = inspect(bind)
    tables = set(schema.get_table_names())
    targets = set(TABLES)
    legacy_tables = {table for table in tables if table.startswith(("library_", "customer_reach_"))}
    if legacy_tables != targets:
        raise RuntimeError("Legacy retirement tables do not match the expected schema")
    for table in sorted(tables - targets):
        if any(fk["referred_table"] in targets for fk in schema.get_foreign_keys(table)):
            raise RuntimeError(f"Retained table references retired data: {table}")
    # A SQLite trigger or view may reference another table without declaring a foreign key.
    objects = bind.exec_driver_sql(
        "SELECT name, tbl_name, sql FROM sqlite_schema WHERE type IN ('view', 'trigger')"
    )
    for name, table, sql in objects:
        if table not in targets and any(target.lower() in sql.lower() for target in targets):
            raise RuntimeError(f"Retained schema object references retired data: {name}")

    for table in TABLES:
        op.drop_table(table)
    if (bind.exec_driver_sql("PRAGMA integrity_check").scalar() != "ok"
            or bind.exec_driver_sql("PRAGMA foreign_key_check").first() is not None):
        raise RuntimeError("Database integrity check failed after legacy retirement")


def downgrade() -> None:
    raise RuntimeError("Legacy module retirement cannot be downgraded")
