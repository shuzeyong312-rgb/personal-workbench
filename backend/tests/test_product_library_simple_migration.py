import sqlite3
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.product_library import router
from app.product_library_service import now
from app.product_library_v2_import import decision_digest
from app.models import LibraryImport

from test_collection_batches_migration import run_command
from test_product_library_v2_migration import seed


@pytest.mark.parametrize("start", ["20261027_19", "20261029_21"])
def test_upgrade_and_restore_isolated_backup(tmp_path, start):
    url, engine = seed(tmp_path)
    if start == "20261029_21":
        run_command(url, start)
    with engine.begin() as connection:
        connection.exec_driver_sql("UPDATE library_products SET price_note='原始备注'")
        connection.exec_driver_sql("INSERT INTO library_imports(import_id,manufacturer_name,created_at,expires_at,status,result) VALUES ('receipt','A','2026-10-29','2026-10-30','committed','{}')")
        if start == "20261029_21":
            connection.exec_driver_sql("UPDATE library_products SET structured_attributes='[{\"key\":\"参数\"}]'")
            connection.exec_driver_sql("INSERT INTO library_product_variants(id,product_id,variant_name,structured_attributes,created_at,updated_at,version) VALUES (50,1,'红色','[{\"key\":\"规格参数\"}]','2026-10-29','2026-10-29',4)")
            connection.exec_driver_sql("INSERT INTO library_product_sources(id,product_id,source_company,source_type,notes,created_at,updated_at,version) VALUES (51,1,'供应商 B','quote','原始条件','2026-10-29','2026-10-29',2)")
            connection.exec_driver_sql("INSERT INTO library_product_prices(id,product_id,variant_id,source_id,price_type,amount_text,currency_code,price_unit,tax_mode,freight_mode,is_default_wholesale,created_at,updated_at,version) VALUES (52,1,50,51,'零售价','88','CNY','件','unknown','unknown',0,'2026-10-29','2026-10-29',3)")
    with engine.connect() as connection:
        before = connection.exec_driver_sql("SELECT * FROM library_products").all()
        receipt = connection.exec_driver_sql("SELECT * FROM library_imports").all()
    database = tmp_path / "isolated.sqlite"
    backup = tmp_path / "backup.sqlite"
    with sqlite3.connect(database) as source, sqlite3.connect(backup) as target:
        source.backup(target)
    run_command(url, "20261030_22")
    with engine.connect() as connection:
        product = connection.exec_driver_sql("SELECT id,manufacturer_name,model,name,wholesale_price_cents,price_note,control_price FROM library_products").one()
        assert tuple(product) == (1, "A", "M", "名称", 1234, "原始备注", None)
        assert connection.exec_driver_sql("SELECT supplier_name,notes FROM library_simple_sources").one() == ("A", "原始备注")
        assert connection.exec_driver_sql("SELECT amount_cents,eligibility,is_current FROM library_simple_quote_versions").one() == (1234, "pending", 1)
        assert connection.exec_driver_sql("SELECT count(*) FROM library_simple_quote_evidence").scalar_one() == 1
        assert connection.exec_driver_sql("SELECT * FROM library_imports").all() == receipt
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        if start == "20261029_21":
            assert connection.exec_driver_sql("SELECT * FROM library_products_history_snapshot").all() == before
            assert connection.exec_driver_sql("SELECT structured_attributes FROM library_products").scalar_one() == '[{"key":"参数"}]'
            assert connection.exec_driver_sql("SELECT id, structured_attributes, version FROM library_product_variants_history_snapshot WHERE id=50").one() == (50, '[{"key":"规格参数"}]', 4)
            assert connection.exec_driver_sql("SELECT id,product_id,variant_id,source_id,price_type,amount_text,version FROM library_product_prices_history_snapshot WHERE id=52").one() == (52, 1, 50, 51, '零售价', '88', 3)
            assert connection.exec_driver_sql("SELECT source_company,notes FROM library_product_sources_history_snapshot WHERE id=51").one() == ('供应商 B', '原始条件')
        with pytest.raises(IntegrityError, match="read-only"):
            connection.exec_driver_sql("DELETE FROM library_product_prices")
        with pytest.raises(IntegrityError, match="immutable"):
            connection.exec_driver_sql("UPDATE library_simple_quote_versions SET amount_cents=999")
        with pytest.raises(IntegrityError, match="cannot be deleted"):
            connection.exec_driver_sql("DELETE FROM library_simple_quote_evidence")
    engine.dispose()
    restored = tmp_path / "restored.sqlite"
    with sqlite3.connect(backup) as source, sqlite3.connect(restored) as target:
        source.backup(target)
    with sqlite3.connect(restored) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == start
        assert connection.execute("SELECT * FROM library_products").fetchall() == [tuple(row) for row in before]
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("start", ["20261027_19", "20261029_21"])
def test_upgrade_failure_rolls_back_all_revisions(tmp_path, start):
    url, engine = seed(tmp_path)
    if start == "20261029_21":
        run_command(url, start)
    with engine.connect() as connection:
        before = connection.exec_driver_sql("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").all()
        products = connection.exec_driver_sql("SELECT * FROM library_products").all()
    def fail(connection, cursor, statement, parameters, context, executemany):
        if "CREATE TABLE library_simple_quote_versions" in statement:
            raise RuntimeError("injected failure")
    event.listen(Engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            run_command(url, "20261030_22")
    finally:
        event.remove(Engine, "before_cursor_execute", fail)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").all() == before
        assert connection.exec_driver_sql("SELECT * FROM library_products").all() == products
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == start
    engine.dispose()


def test_conflicting_legacy_backfill_refuses_conversion(tmp_path):
    url, engine = seed(tmp_path)
    run_command(url, "20261029_21")
    with engine.begin() as connection:
        connection.exec_driver_sql("UPDATE library_product_prices SET amount_text='99'")
    with pytest.raises(RuntimeError, match="Legacy price conflict for product id=1"):
        run_command(url, "20261030_22")
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "20261029_21"
        assert connection.exec_driver_sql("SELECT amount_text FROM library_product_prices").scalar_one() == "99"
        assert connection.exec_driver_sql("SELECT count(*) FROM sqlite_master WHERE name='library_history_manifest'").scalar_one() == 0
    engine.dispose()


def test_duplicate_identity_from_old_database_reports_ids_without_writes(tmp_path):
    url, engine = seed(tmp_path, duplicate=True)
    with pytest.raises(RuntimeError, match="identity conflicts.*manufacturer_name") as error:
        run_command(url, "20261030_22")
    assert "'id': 1" in str(error.value) and "'id': 2" in str(error.value)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "20261027_19"
        assert connection.exec_driver_sql("SELECT count(*) FROM library_products").scalar_one() == 2
    engine.dispose()


def test_migrated_database_supports_simple_product_quote_and_archive(tmp_path):
    url, engine = seed(tmp_path)
    run_command(url, '20261030_22')
    app = FastAPI()
    app.include_router(router)
    def session():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = session
    with TestClient(app) as client:
        old = client.get('/api/product-library/products/1').json()
        assert old['quotes'][0]['eligibility'] == 'pending'
        created = client.post('/api/product-library/products', json={'name': '新产品', 'model': 'NEW', 'control_price': '控价30'})
        assert created.status_code == 201, created.text
        product = created.json()
        base = f"/api/product-library/products/{product['id']}"
        quote = client.post(base + '/manual-quotes', json={'product_version': product['version'], 'supplier': 'B', 'variant': None, 'price_text': '12', 'conditions': '未税，运费另计', 'idempotency_key': 'migrated-test'})
        assert quote.status_code == 201, quote.text
        review = client.post(base + f"/quotes/{quote.json()['quote_version_id']}/review", json={'product_version': product['version'] + 1, 'status': 'eligible', 'reason': '已核对出厂价', 'source_id': quote.json()['source_id']})
        assert review.status_code == 200, review.text
        assert client.request('DELETE', base, json={'version': review.json()['product_version']}).status_code == 204
        assert client.get(base).status_code == 404
        restored = client.post(base + '/restore', json={'version': review.json()['product_version'] + 1})
        assert restored.status_code == 200
        assert client.get(base).json()['quotes'][0]['eligibility'] == 'pending'
    with engine.connect() as connection:
        assert connection.exec_driver_sql('PRAGMA integrity_check').scalar_one() == 'ok'
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
    engine.dispose()


def test_old_committed_v2_receipt_replays_after_forward_migration(tmp_path):
    url, engine = seed(tmp_path)
    run_command(url, '20261029_21')
    import_id = str(uuid4())
    payload = {'decisions': [{'row_key': {'sheet': '产品数据', 'temp_id': 'P'}, 'action': 'skip_product'}], 'confirmed_attachments_not_imported': True}
    original = {'import_id': import_id, 'template_version': 2, 'rows': [{'outcome': 'skipped'}]}
    with Session(engine) as db:
        db.add(LibraryImport(import_id=import_id, manufacturer_name='A', created_at=now(), expires_at=now(), status='committed', decision_digest=decision_digest(payload), result=original))
        db.commit()
    run_command(url, '20261030_22')
    app = FastAPI()
    app.include_router(router)
    def session():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = session
    with TestClient(app) as client:
        assert client.get(f'/api/product-library/imports/{import_id}').json() == original
        replay = client.post(f'/api/product-library/imports/{import_id}/confirm', json=payload)
        assert replay.status_code == 200 and replay.json() == original
    engine.dispose()
