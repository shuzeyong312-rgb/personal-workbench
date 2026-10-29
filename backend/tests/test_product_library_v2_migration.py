"""Only fresh temporary databases are used; never the working library."""
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.database import DATABASE_FILE
from test_collection_batches_migration import run_command

OLD = "20261027_19"
NEW = "20261029_20"


def seed(tmp_path, model="M", duplicate=False):
    path = (tmp_path / "isolated.sqlite").resolve()
    assert path != DATABASE_FILE.resolve() and path.is_relative_to(tmp_path.resolve())
    url = f"sqlite:///{path.as_posix()}"
    run_command(url, OLD)
    engine = create_engine(url)
    with engine.begin() as connection:
        for company in (["A", "B"] if duplicate else ["A"]):
            connection.execute(text("INSERT INTO library_products(manufacturer_name,model,name,wholesale_price_cents,created_at,updated_at,version) VALUES (:company,:model,'名称',1234,'2026-10-29','2026-10-29',3)"), {"company": company, "model": model})
    return url, engine


def state(engine):
    with engine.connect() as connection:
        return connection.exec_driver_sql("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").all(), connection.exec_driver_sql("SELECT * FROM library_products").all(), connection.exec_driver_sql("SELECT * FROM alembic_version").all()


@pytest.mark.parametrize("model", [None, "M"])
def test_identity_collision_refuses_without_writes(tmp_path, model):
    url, engine = seed(tmp_path, model, duplicate=True)
    before = state(engine)
    with pytest.raises(RuntimeError, match="identity conflicts.*manufacturer_name"):
        run_command(url, NEW)
    assert state(engine) == before
    engine.dispose()


@pytest.mark.parametrize("stage", ["create", "drop", "stamp"])
def test_identity_upgrade_failure_is_atomic(tmp_path, stage):
    url, engine = seed(tmp_path)
    before = state(engine)
    def fail(connection, cursor, statement, parameters, context, executemany):
        if (stage == "create" and "CREATE UNIQUE INDEX uq_library_products_null_model_name" in statement
            or stage == "drop" and "DROP INDEX uq_library_products_manufacturer_model_name" in statement
            or stage == "stamp" and statement.startswith("UPDATE alembic_version") and NEW in (statement + str(parameters))):
            raise RuntimeError("injected")
    event.listen(Engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            run_command(url, NEW)
    finally:
        event.remove(Engine, "before_cursor_execute", fail)
    assert state(engine) == before
    run_command(url, NEW)
    engine.dispose()


def test_global_identity_constraints_and_normalization(tmp_path):
    url, engine = seed(tmp_path)
    before = state(engine)[1]
    run_command(url, NEW)
    assert state(engine)[1] == before
    with engine.begin() as connection:
        insert = text("INSERT INTO library_products(manufacturer_name,model,name,created_at,updated_at,version) VALUES ('B',:model,:name,'2026-10-29','2026-10-29',1)")
        with pytest.raises(IntegrityError):
            connection.execute(insert, {"model": "M", "name": "名称"})
        for model, name in [(None, "名称"), ("m", "名称"), ("M", "不同名称")]:
            connection.execute(insert, {"model": model, "name": name})
        with pytest.raises(IntegrityError):
            connection.execute(insert, {"model": None, "name": "名称"})
    with pytest.raises(RuntimeError, match="Unsafe downgrade"):
        run_command(url, OLD, downgrade=True)
    engine.dispose()


def test_noncanonical_identity_is_not_rewritten(tmp_path):
    url, engine = seed(tmp_path)
    with engine.begin() as connection:
        connection.execute(text("UPDATE library_products SET model=' M '"))
    before = state(engine)
    with pytest.raises(RuntimeError, match="Noncanonical"):
        run_command(url, NEW)
    assert state(engine) == before
    engine.dispose()


def test_details_backfill_preserves_legacy_rows_receipts_and_amount(tmp_path):
    url, engine = seed(tmp_path)
    with engine.begin() as connection:
        connection.exec_driver_sql("INSERT INTO library_imports(import_id,manufacturer_name,created_at,expires_at,status,result) VALUES ('old','A','2026-10-29','2026-10-30','committed','{\"kept\":true}')")
        before = connection.exec_driver_sql('SELECT * FROM library_products').all()
        receipts = connection.exec_driver_sql('SELECT * FROM library_imports').all()
    run_command(url, '20261029_21')
    with engine.connect() as connection:
        after = connection.exec_driver_sql('SELECT * FROM library_products').all()
        assert [tuple(row[:len(before[0])]) for row in after] == [tuple(row) for row in before]
        assert connection.exec_driver_sql('SELECT * FROM library_imports').all() == receipts
        assert connection.exec_driver_sql('SELECT amount_text,currency_code,price_unit,is_default_wholesale FROM library_product_prices').one() == ('12.34','CNY','件',1)
        assert connection.exec_driver_sql('SELECT notes,claimed_manufacturer_name,source_date FROM library_product_sources').one() == ('legacy_backfill',None,None)
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
    current = state(engine)
    with pytest.raises(RuntimeError, match='Unsafe downgrade'):
        run_command(url, OLD, downgrade=True)
    assert state(engine) == current
    engine.dispose()


@pytest.mark.parametrize('stage',['ddl','backfill','stamp'])
def test_complete_v2_upgrade_failure_restores_prior_revision(tmp_path,stage):
    url,engine=seed(tmp_path)
    before=state(engine)
    def fail(connection,cursor,statement,parameters,context,executemany):
        if (stage=='ddl' and 'CREATE TABLE library_product_prices' in statement
            or stage=='backfill' and 'INSERT INTO library_product_prices' in statement
            or stage=='stamp' and statement.startswith('UPDATE alembic_version') and '20261029_21' in statement+str(parameters)):
            raise RuntimeError('injected')
    event.listen(Engine,'before_cursor_execute',fail)
    try:
        with pytest.raises(RuntimeError,match='injected'):
            run_command(url,'20261029_21')
    finally:
        event.remove(Engine,'before_cursor_execute',fail)
    assert state(engine)==before
    run_command(url,'20261029_21')
    engine.dispose()
