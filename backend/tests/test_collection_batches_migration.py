from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

import app.database as database


BACKEND_ROOT = Path(__file__).parents[1]


def run_command(database_url: str, revision: str, *, downgrade: bool = False) -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    original_url = database.DATABASE_URL
    database.DATABASE_URL = database_url
    try:
        (command.downgrade if downgrade else command.upgrade)(config, revision)
    finally:
        database.DATABASE_URL = original_url


def test_collection_batches_migration_preserves_legacy_runs_and_round_trips(tmp_path, monkeypatch) -> None:
    path = tmp_path / "collection-batches.sqlite"
    database_url = f"sqlite:///{path.as_posix()}"
    monkeypatch.setattr(database, "DATABASE_URL", database_url)
    run_command(database_url, "20261010_13")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO competitors (
                platform, offer_id, url, title, shop_name, main_image_url, status,
                is_active, created_at, updated_at, last_collected_at
            ) VALUES ('1688', 'legacy-offer', 'https://detail.1688.com/offer/legacy-offer.html',
                      'legacy', 'legacy shop', NULL, 'unknown', 1,
                      '2026-10-12 00:00:00', '2026-10-12 00:00:00', NULL)
        """))
        connection.execute(text("""
            INSERT INTO collection_runs (competitor_id, started_at, status, operating_metrics_status)
            VALUES (1, '2026-10-12 00:00:00', 'success', 'not_attempted')
        """))
    engine.dispose()

    run_command(database_url, "20261012_14")
    engine = create_engine(database_url)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT collection_batch_item_id, attempt_number FROM collection_runs WHERE id=1")).one() == (None, None)
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
        assert connection.execute(text("PRAGMA integrity_check")).scalar_one() == "ok"
        assert {"collection_batches", "collection_batch_items"}.issubset(inspect(connection).get_table_names())
    engine.dispose()

    run_command(database_url, "20261010_13", downgrade=True)
    engine = create_engine(database_url)
    with engine.connect() as connection:
        assert "collection_batches" not in inspect(connection).get_table_names()
        assert "collection_batch_items" not in inspect(connection).get_table_names()
        assert "collection_batch_item_id" not in {column["name"] for column in inspect(connection).get_columns("collection_runs")}
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    engine.dispose()
