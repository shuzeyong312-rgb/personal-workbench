from pathlib import Path
import pytest
from sqlalchemy import create_engine, text, inspect
from test_collection_batches_migration import run_command


def test_unification_upgrade_preserves_history_and_empty_extension_downgrades(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'v13.sqlite').as_posix()}"
    run_command(url, '20261012_14')
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(text("INSERT INTO competitors(platform,offer_id,url,status,is_active,ownership,group_role,created_at,updated_at) VALUES('1688','101','https://detail.1688.com/offer/101.html','active',1,'competitor','competitor','2026-10-01','2026-10-01')"))
        db.execute(text("INSERT INTO collection_runs(competitor_id,started_at,status,operating_metrics_status) VALUES(1,'2026-10-01','success','not_attempted')"))
        db.execute(text("INSERT INTO collection_batches(task_id,trigger_kind,created_at,lifecycle_status,settings_snapshot,planned_products) VALUES('legacy','manual_selected','2026-10-01','created','{}',1)"))
        db.execute(text("INSERT INTO collection_batch_items(batch_id,position,competitor_id) VALUES(1,0,1)"))
        db.execute(text("INSERT INTO collection_runs(competitor_id,collection_batch_item_id,attempt_number,attempt_kind,started_at,status,operating_metrics_status,error_message) VALUES(1,1,1,'first_pass','2026-10-02','success','partial','original reason')"))
        db.execute(text("INSERT INTO operating_metric_observations(competitor_id,collection_run_id,platform,offer_id,metric_key,status,raw_value,source,observed_at,reason) VALUES(1,2,'1688','101','monthly_deal','placeholder','-','html','2026-10-02','source placeholder')"))
        db.execute(text("INSERT INTO product_snapshots(competitor_id,captured_at,title,shop_name,product_status,collection_source) VALUES(1,'2026-10-02','legacy product','legacy shop','active','html')"))
        db.execute(text("INSERT INTO sku_snapshots(product_snapshot_id,sku_id,sku_name,stock,price) VALUES(1,'sku-1','legacy sku',7,12.34)"))
        preserved = {table: db.execute(text(f'SELECT * FROM {table} ORDER BY id')).all() for table in ('collection_runs','operating_metric_observations','product_snapshots','sku_snapshots')}
    engine.dispose()
    run_command(url, '20261015_15')
    engine = create_engine(url)
    with engine.connect() as db:
        assert db.execute(text('SELECT collection_batch_item_id FROM collection_runs WHERE id=1')).scalar() is None
        assert db.execute(text('SELECT identity_state FROM collection_batch_items')).scalar() == 'linked'
        assert db.execute(text('PRAGMA integrity_check')).scalar() == 'ok'
        assert db.execute(text('PRAGMA foreign_key_check')).all() == []
        for table, rows in preserved.items():
            assert db.execute(text(f'SELECT * FROM {table} ORDER BY id')).all() == rows
        names = inspect(db).get_table_names()
        assert 'collection_add_inputs' in names
    engine.dispose()
    run_command(url, '20261012_14', downgrade=True)
    engine = create_engine(url)
    with engine.connect() as db:
        assert db.execute(text('SELECT count(*) FROM collection_runs')).scalar() == 2
        assert db.execute(text('PRAGMA foreign_key_check')).all() == []
        for table, rows in preserved.items():
            assert db.execute(text(f'SELECT * FROM {table} ORDER BY id')).all() == rows
        assert 'collection_add_inputs' not in inspect(db).get_table_names()
    engine.dispose()


def test_unification_refuses_lossy_downgrade_before_schema_changes(tmp_path):
    url = f"sqlite:///{(tmp_path / 'v13-facts.sqlite').as_posix()}"
    run_command(url, '20261015_15')
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(text("INSERT INTO collection_batches(task_id,trigger_kind,request_fingerprint,created_at,lifecycle_status,settings_snapshot,planned_products) VALUES('new','add_links','hash','2026-10-15','created','{}',0)"))
    engine.dispose()
    with pytest.raises(RuntimeError, match='refusing lossy'):
        run_command(url, '20261012_14', downgrade=True)
    engine = create_engine(url)
    with engine.connect() as db:
        assert db.execute(text('SELECT version_num FROM alembic_version')).scalar() == '20261015_15'
        assert db.execute(text('SELECT count(*) FROM collection_batches')).scalar() == 1
        assert 'collection_add_inputs' in inspect(db).get_table_names()
        assert db.execute(text('PRAGMA foreign_key_check')).all() == []
    engine.dispose()
