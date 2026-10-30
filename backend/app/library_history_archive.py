"""Create immutable snapshots of the library tables present before conversion.

The caller must hold the migration's SQLite write transaction.
"""
from sqlalchemy import text
from sqlalchemy.engine import Connection


HISTORICAL_TABLES = (
    "library_products",
    "library_product_variants",
    "library_product_sources",
    "library_product_prices",
    "library_imports",
)


def archive_library_history(connection: Connection) -> None:
    if not connection.connection.driver_connection.in_transaction:
        raise RuntimeError("Library archive requires an active SQLite write transaction")
    existing = set(connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).scalars())
    if not {"library_products", "library_imports"}.issubset(existing):
        raise RuntimeError("Required library tables are missing")

    connection.exec_driver_sql("CREATE TABLE library_history_manifest (table_name TEXT PRIMARY KEY, present INTEGER NOT NULL CHECK (present IN (0, 1)))")
    for table in HISTORICAL_TABLES:
        present = table in existing
        connection.execute(text("INSERT INTO library_history_manifest VALUES (:name, :present)"), {"name": table, "present": int(present)})
        if not present:
            continue
        archive = f"{table}_history_snapshot"
        connection.exec_driver_sql(f'CREATE TABLE "{archive}" AS SELECT * FROM "{table}"')
        for action in ("INSERT", "UPDATE", "DELETE"):
            connection.exec_driver_sql(
                f'CREATE TRIGGER "{archive}_no_{action.lower()}" BEFORE {action} ON "{archive}" '
                "BEGIN SELECT RAISE(ABORT, 'library history is read-only'); END"
            )
    for action in ("INSERT", "UPDATE", "DELETE"):
        connection.exec_driver_sql(
            f'CREATE TRIGGER "library_history_manifest_no_{action.lower()}" BEFORE {action} ON library_history_manifest '
            "BEGIN SELECT RAISE(ABORT, 'library history is read-only'); END"
        )
