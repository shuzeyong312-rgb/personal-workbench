from contextlib import closing
import sqlite3
from argparse import Namespace
from unittest.mock import Mock

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

from app import database, main
from app.retirement import RETIREMENT_REVISION
from test_collection_batches_migration import BACKEND_ROOT, run_command
from test_product_library_v2_migration import seed

ALLOW = ("retire_legacy_modules=1",)
OLD = ("20261029_21", "20261030_22")


def snapshot(path):
    with closing(sqlite3.connect(path)) as db:
        return list(db.iterdump())


def check_retired(url):
    engine = create_engine(url)
    try:
        with engine.connect() as db:
            assert db.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == RETIREMENT_REVISION
            assert db.exec_driver_sql("PRAGMA integrity_check").scalar_one() == "ok"
            assert not db.exec_driver_sql("PRAGMA foreign_key_check").all()
            assert not db.exec_driver_sql(
                "SELECT name FROM sqlite_schema WHERE tbl_name GLOB 'library_*' "
                "OR tbl_name GLOB 'customer_reach_*'"
            ).all()
    finally:
        engine.dispose()


@pytest.fixture(params=OLD)
def existing(request, tmp_path):
    url, engine = seed(tmp_path)
    run_command(url, request.param)
    with engine.begin() as db:
        db.exec_driver_sql("INSERT INTO system_settings (key, value) VALUES ('retained-fixture', 'value')")
        db.exec_driver_sql(
            "INSERT INTO customer_reach_tasks (id, customer_nickname, message_text, product_url, "
            "content_fingerprint, status, step, created_at) "
            "VALUES ('task', 'nickname', 'text', 'url', 'hash', 'pending', 'pending', '2026-11-23')"
        )
        db.exec_driver_sql(
            "INSERT INTO customer_reach_campaigns (id, customer_category, message_text, product_url, "
            "content_fingerprint, status, step, recipients, created_at) "
            "VALUES ('campaign', 'ordered', 'text', 'url', 'hash', 'pending', 'pending', '[]', '2026-11-23')"
        )
        db.exec_driver_sql(
            "INSERT INTO library_imports (import_id,manufacturer_name,created_at,expires_at,status,result) "
            "VALUES ('receipt','A','2026-10-29','2026-10-30','committed','{}')"
        )
    yield url, engine, tmp_path / "isolated.sqlite"
    engine.dispose()


def retained(path):
    with closing(sqlite3.connect(path)) as db:
        objects = db.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE tbl_name <> 'alembic_version' "
            "AND tbl_name NOT GLOB 'library_*' AND tbl_name NOT GLOB 'customer_reach_*' "
            "AND name NOT GLOB 'sqlite_autoindex_*' ORDER BY type,name"
        ).fetchall()
        data = {}
        for kind, name, _, _ in objects:
            if kind == "table":
                rows = db.execute('SELECT * FROM "' + name.replace('"', '""') + '"').fetchall()
                if name == "sqlite_sequence":
                    rows = [row for row in rows if not row[0].startswith(("library_", "customer_reach_"))]
                data[name] = sorted(rows, key=repr)
        return objects, data


def test_explicit_upgrade_retires_data_and_preserves_other_tables(existing):
    url, _, path = existing
    before = retained(path)
    run_command(url, "head", args=ALLOW)
    check_retired(url)
    assert retained(path) == before
    run_command(url, "head")


def test_ordinary_upgrade_and_backend_startup_refuse_old_database(existing, monkeypatch):
    url, engine, path = existing
    before = snapshot(path)
    with pytest.raises(RuntimeError, match="explicit cutover"):
        run_command(url, "head")
    monkeypatch.setattr(main, "engine", engine)
    recovery = Mock()
    scheduler = Mock()
    monkeypatch.setattr(main, "recover_interrupted_batches", recovery)
    monkeypatch.setattr(main, "_daily_collection_loop", scheduler)
    with pytest.raises(RuntimeError, match="Database is not ready"):
        with TestClient(main.app):
            pytest.fail("startup should refuse a legacy database")
    recovery.assert_not_called()
    scheduler.assert_not_called()
    assert snapshot(path) == before


@pytest.mark.parametrize("failure_at", ("DROP TABLE library_simple_quote_versions", "UPDATE alembic_version"))
def test_retirement_rolls_back_schema_data_and_revision(existing, failure_at):
    url, _, path = existing
    before = snapshot(path)
    observed = []

    def on_statement(connection, cursor, sql, parameters, context, executemany):
        sql = sql.strip()
        if sql.startswith("DROP TABLE library_simple"):
            driver = connection.connection.driver_connection
            assert driver.in_transaction
            assert driver.execute("PRAGMA foreign_keys").fetchone() == (1,)
            observed.append(sql)
        if failure_at in sql and (failure_at.startswith("DROP") or RETIREMENT_REVISION in sql or RETIREMENT_REVISION in parameters):
            raise RuntimeError("injected retirement failure")

    event.listen(Engine, "before_cursor_execute", on_statement)
    try:
        with pytest.raises(RuntimeError, match="injected retirement failure"):
            run_command(url, "head", args=ALLOW)
    finally:
        event.remove(Engine, "before_cursor_execute", on_statement)
    assert observed
    assert snapshot(path) == before


def test_empty_database_initializes_and_backend_uses_retained_api(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'fresh.sqlite').as_posix()}"
    run_command(url, "head")
    check_retired(url)
    engine = create_engine(url, connect_args={"check_same_thread": False})
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "acquire_backend_lease", lambda _: Mock())
    monkeypatch.setenv("PERSONAL_WORKBENCH_DISABLE_SCHEDULER", "1")
    try:
        with TestClient(main.app) as client:
            assert client.get("/api/health").status_code == 200
            paths = client.get("/openapi.json").json()["paths"]
            assert "/api/competitors" in paths
            for prefix, endpoint in [("/api/product-library", "/products"), ("/api/customer-reach", "/tasks")]:
                assert not any(path.startswith(prefix) for path in paths)
                assert client.get(prefix + endpoint).status_code == 404
    finally:
        engine.dispose()


def test_refuses_unversioned_nonempty_database_and_offline_sql(tmp_path):
    path = tmp_path / "unversioned.sqlite"
    url = f"sqlite:///{path.as_posix()}"
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE retained(id INTEGER PRIMARY KEY)")
    before = snapshot(path)
    with pytest.raises(RuntimeError, match="Unsupported database revision"):
        run_command(url, "head", args=ALLOW)
    with pytest.raises(RuntimeError, match="requires an online SQLite connection"):
        run_command(url, "head", args=ALLOW, sql=True)
    assert snapshot(path) == before


def test_rejects_retained_dependency(existing):
    url, engine, path = existing
    with engine.begin() as db:
        db.exec_driver_sql("CREATE VIEW retained_view AS SELECT id FROM library_products")
    before = snapshot(path)
    with pytest.raises(RuntimeError, match="Retained schema object"):
        run_command(url, "head", args=ALLOW)
    assert snapshot(path) == before

def test_interrupted_fresh_install_requires_explicit_cutover(tmp_path):
    path = tmp_path / "interrupted.sqlite"
    url = f"sqlite:///{path.as_posix()}"
    seen = []

    def fail(connection, cursor, sql, parameters, context, executemany):
        if sql.strip() == "DROP TABLE library_simple_quote_evidence":
            driver = connection.connection.driver_connection
            assert driver.in_transaction and driver.execute("PRAGMA foreign_keys").fetchone() == (1,)
            seen.append(sql)
            raise RuntimeError("failed after historical replay")

    event.listen(Engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="failed after historical replay"):
            run_command(url, "head")
    finally:
        event.remove(Engine, "before_cursor_execute", fail)
    assert seen
    before = snapshot(path)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("20261030_22",)
    with pytest.raises(RuntimeError, match="explicit cutover"):
        run_command(url, "head")
    assert snapshot(path) == before


def test_explicit_parameter_does_not_allow_stamping_retirement(existing, monkeypatch):
    url, _, path = existing
    before = snapshot(path)
    config = Config(str(BACKEND_ROOT / "alembic.ini"), cmd_opts=Namespace(x=list(ALLOW)))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    monkeypatch.setattr(database, "DATABASE_URL", url)
    with pytest.raises(RuntimeError, match="not a revision stamp"):
        command.stamp(config, "head")
    assert snapshot(path) == before
