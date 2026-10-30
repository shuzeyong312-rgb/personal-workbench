import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.library_history_archive import HISTORICAL_TABLES, archive_library_history
from test_product_library_v2_migration import seed
from test_collection_batches_migration import run_command


@pytest.mark.parametrize("revision", ["20261027_19", "20261029_21"])
def test_snapshots_preserve_present_tables_and_reject_writes(tmp_path, revision):
    url, engine = seed(tmp_path)
    if revision == "20261029_21":
        run_command(url, revision)
    with engine.begin() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        connection.exec_driver_sql("UPDATE library_products SET price_note='条件原文'")
        if revision == "20261029_21":
            connection.exec_driver_sql("UPDATE library_products SET structured_attributes='[{\"name\":\"参数\"}]'")
        archive_library_history(connection)
    with engine.connect() as connection:
        manifest = dict(connection.exec_driver_sql("SELECT table_name, present FROM library_history_manifest").all())
        for table in HISTORICAL_TABLES:
            assert manifest[table] == (revision == "20261029_21" or table in ("library_products", "library_imports"))
            if manifest[table]:
                assert connection.exec_driver_sql(f'SELECT * FROM "{table}"').all() == connection.exec_driver_sql(f'SELECT * FROM "{table}_history_snapshot"').all()
                with pytest.raises(IntegrityError, match="read-only"):
                    connection.exec_driver_sql(f'INSERT INTO "{table}_history_snapshot" DEFAULT VALUES')
        with pytest.raises(IntegrityError, match="read-only"):
            connection.exec_driver_sql("UPDATE library_history_manifest SET present=0")
    engine.dispose()


def test_archive_failure_rolls_back_schema_and_data(tmp_path):
    url, engine = seed(tmp_path)
    run_command(url, "20261029_21")
    with engine.connect() as connection:
        before = connection.exec_driver_sql("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").all()

    def fail(connection, cursor, statement, parameters, context, executemany):
        if 'CREATE TABLE "library_product_sources_history_snapshot"' in statement:
            raise RuntimeError("injected failure")

    event.listen(Engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            with engine.begin() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                archive_library_history(connection)
    finally:
        event.remove(Engine, "before_cursor_execute", fail)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").all() == before
        assert connection.exec_driver_sql("SELECT manufacturer_name, wholesale_price_cents FROM library_products").one() == ("A", 1234)
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "20261029_21"
    engine.dispose()
