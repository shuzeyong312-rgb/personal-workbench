import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from test_collection_batches_migration import run_command


def test_upgrade_preserves_existing_data_and_seeds_once(tmp_path, monkeypatch):
    path = Path(__file__).parents[1] / "alembic" / "versions" / "20261027_19_toolbox.py"
    spec = importlib.util.spec_from_file_location("toolbox_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE existing (value TEXT)"))
        connection.execute(text("INSERT INTO existing VALUES ('preserved')"))
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        module.upgrade()
        assert connection.execute(text("SELECT value FROM existing")).scalar_one() == "preserved"
        assert connection.execute(text("SELECT count(*) FROM toolbox_items")).scalar_one() == 3
        assert connection.execute(text("SELECT favorite FROM toolbox_items WHERE name = 'iLovePDF'")).scalar_one() == 1


def test_real_alembic_upgrade_is_repeatable_and_keeps_favorites(tmp_path):
    url = f"sqlite:///{(tmp_path / 'upgrade.db').as_posix()}"
    run_command(url, "20261023_18")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO competitor_groups (name, created_at) VALUES ('existing', '2026-01-01')"))
    run_command(url, "20261027_19")
    with engine.begin() as connection:
        connection.execute(text("UPDATE toolbox_items SET favorite = 0 WHERE name = 'iLovePDF'"))
    run_command(url, "20261027_19")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM toolbox_items")).scalar_one() == 3
        assert connection.execute(text("SELECT favorite FROM toolbox_items WHERE name = 'iLovePDF'")).scalar_one() == 0
        assert connection.execute(text("SELECT name FROM competitor_groups")).scalar_one() == "existing"
        assert connection.execute(text("PRAGMA integrity_check")).scalar_one() == "ok"
    engine.dispose()
