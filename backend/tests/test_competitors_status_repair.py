import importlib.util
from pathlib import Path
import sqlite3

import pytest

SCRIPT = Path(__file__).parents[1] / 'scripts/repair_competitors_status.py'
spec = importlib.util.spec_from_file_location('status_repair', SCRIPT)
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


def fixture_db(path, check=''):
    with sqlite3.connect(path) as db:
        db.executescript(f"""CREATE TABLE competitors(id INTEGER PRIMARY KEY, status TEXT NOT NULL {check});
        CREATE TABLE history(id INTEGER PRIMARY KEY, competitor_id INTEGER REFERENCES competitors(id));
        CREATE TABLE audit(id INTEGER);
        CREATE INDEX ix_status ON competitors(status);
        CREATE TRIGGER record_update AFTER UPDATE ON competitors BEGIN INSERT INTO audit VALUES(NEW.id); END;
        INSERT INTO competitors VALUES(1,'active'); INSERT INTO history VALUES(7,1);""")


def test_rebuild_preserves_history_objects_and_rejects_invalid_status(tmp_path):
    path = tmp_path/'missing.sqlite'; fixture_db(path)
    with sqlite3.connect(path) as db:
        before = repair.facts(db)
        ddl = db.execute("SELECT type,name,sql FROM sqlite_master WHERE type IN ('index','trigger') ORDER BY name").fetchall()
    assert repair.repair_database(path)['changed'] is False
    assert repair.repair_database(path, apply=True, backup_path=tmp_path/'backup.sqlite')['changed'] is True
    with sqlite3.connect(path) as db:
        assert repair.facts(db) == before
        assert db.execute("SELECT type,name,sql FROM sqlite_master WHERE type IN ('index','trigger') ORDER BY name").fetchall() == ddl
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        with pytest.raises(sqlite3.IntegrityError): db.execute("UPDATE competitors SET status='invalid'")
        db.rollback()
        for value in repair.VALID:
            db.execute('UPDATE competitors SET status=?', (value,)); db.rollback()
    assert repair.repair_database(path, apply=True)['changed'] is False


@pytest.mark.parametrize('check', ["CHECK(status IN ('offline','active','unknown'))", "CONSTRAINT another_name CHECK(status IN ('unknown','active','offline'))"])
def test_semantically_healthy_database_is_byte_identical_noop(tmp_path, check):
    path=tmp_path/'healthy.sqlite'; fixture_db(path,check); before=path.read_bytes()
    assert repair.repair_database(path,apply=True)['changed'] is False
    assert path.read_bytes() == before


def test_illegal_data_is_blocked_without_changes(tmp_path):
    path=tmp_path/'invalid.sqlite'; fixture_db(path)
    with sqlite3.connect(path) as db: db.execute("UPDATE competitors SET status='unexpected'")
    before=path.read_bytes()
    with pytest.raises(RuntimeError,match='invalid status rows'):
        repair.repair_database(path,apply=True,backup_path=tmp_path/'backup.sqlite')
    assert path.read_bytes()==before
    assert not (tmp_path/'backup.sqlite').exists()


def test_failure_after_drop_rolls_back_everything(tmp_path,monkeypatch):
    path=tmp_path/'rollback.sqlite'; fixture_db(path)
    with sqlite3.connect(path) as db:
        before=repair.facts(db); schema=db.execute('SELECT type,name,sql FROM sqlite_master ORDER BY name').fetchall()
    original=sqlite3.connect
    class FailRename(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql.startswith('ALTER TABLE'): raise RuntimeError('injected after drop')
            return super().execute(sql,*args,**kwargs)
    def connect(*args,**kwargs):
        if kwargs.get('isolation_level','default') is None: kwargs['factory']=FailRename
        return original(*args,**kwargs)
    monkeypatch.setattr(repair.sqlite3,'connect',connect)
    with pytest.raises(RuntimeError,match='injected'):
        repair.repair_database(path,apply=True,backup_path=tmp_path/'backup.sqlite')
    with original(path) as db:
        assert repair.facts(db)==before
        assert db.execute('SELECT type,name,sql FROM sqlite_master ORDER BY name').fetchall()==schema
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]



def test_conflicting_named_constraint_is_blocked(tmp_path):
    path=tmp_path/'conflict.sqlite'
    fixture_db(path,"CONSTRAINT ck_competitors_status CHECK(status != 'invalid')")
    before=path.read_bytes()
    with pytest.raises(RuntimeError,match='different expression'):
        repair.repair_database(path,apply=True,backup_path=tmp_path/'backup.sqlite')
    assert path.read_bytes()==before
