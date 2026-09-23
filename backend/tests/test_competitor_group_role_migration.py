from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

import app.database as database


BACKEND_ROOT = Path(__file__).parents[1]


def migrate(database_url: str, revision: str, *, downgrade: bool = False) -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    original_url = database.DATABASE_URL
    database.DATABASE_URL = database_url
    try:
        (command.downgrade if downgrade else command.upgrade)(config, revision)
    finally:
        database.DATABASE_URL = original_url


def database_url(directory: str) -> str:
    return f"sqlite:///{(Path(directory) / 'migration.db').as_posix()}"


def insert_previous_head_rows(url: str) -> None:
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO competitor_groups (name, created_at) VALUES ('A19', '2026-09-20')"))
        connection.execute(text("""
            INSERT INTO competitors (group_id, platform, offer_id, url, title, shop_name, status, is_active, created_at, updated_at)
            VALUES (1, '1688', '123', 'https://detail.1688.com/offer/123.html', '基准商品', '店铺', 'active', 1, '2026-09-20', '2026-09-20')
        """))
        connection.execute(text("""
            INSERT INTO product_snapshots (competitor_id, captured_at, title, shop_name, price_min, price_max, product_status, collection_source)
            VALUES (1, '2026-09-20', '基准商品', '店铺', 20, 30, 'active', 'html')
        """))
        connection.execute(text("INSERT INTO sku_snapshots (product_snapshot_id, sku_id, sku_name) VALUES (1, 'sku-1', '红色')"))
        connection.execute(text("INSERT INTO collection_runs (competitor_id, started_at, status) VALUES (1, '2026-09-20', 'success')"))
        connection.execute(text("""
            INSERT INTO change_events (competitor_id, snapshot_id, collection_run_id, change_type, detected_at)
            VALUES (1, 1, 1, 'price_increase', '2026-09-20')
        """))
    engine.dispose()


def test_group_role_migration_preserves_history_and_enforces_sqlite_invariants() -> None:
    with TemporaryDirectory() as temporary_directory:
        url = database_url(temporary_directory)
        migrate(url, "20260923_10")
        insert_previous_head_rows(url)
        migrate(url, "20260923_11")

        engine = create_engine(url)
        with engine.begin() as connection:
            assert connection.execute(text("SELECT group_role FROM competitors WHERE id = 1")).scalar_one() == "competitor"
            assert connection.execute(text("SELECT COUNT(*) FROM product_snapshots")).scalar_one() == 1
            assert connection.execute(text("SELECT COUNT(*) FROM sku_snapshots")).scalar_one() == 1
            assert connection.execute(text("SELECT COUNT(*) FROM collection_runs")).scalar_one() == 1
            assert connection.execute(text("SELECT COUNT(*) FROM change_events")).scalar_one() == 1
            connection.execute(text("INSERT INTO competitor_groups (name, created_at) VALUES ('X6', '2026-09-21')"))
            connection.execute(text("INSERT INTO competitors (group_id, platform, offer_id, url, status, is_active, created_at, updated_at, group_role) VALUES (2, '1688', '456', 'https://detail.1688.com/offer/456.html', 'unknown', 1, '2026-09-21', '2026-09-21', 'own')"))
            connection.execute(text("INSERT INTO competitors (group_id, platform, offer_id, url, status, is_active, created_at, updated_at, group_role) VALUES (1, '1688', '789', 'https://detail.1688.com/offer/789.html', 'unknown', 1, '2026-09-21', '2026-09-21', 'own')"))
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(text("UPDATE competitors SET group_role = 'fake' WHERE id = 1"))
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(text("UPDATE competitors SET group_id = NULL, group_role = 'own' WHERE id = 1"))
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(text("INSERT INTO competitors (group_id, platform, offer_id, url, status, is_active, created_at, updated_at, group_role) VALUES (1, '1688', '999', 'https://detail.1688.com/offer/999.html', 'unknown', 1, '2026-09-21', '2026-09-21', 'own')"))
            assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
            assert connection.execute(text("SELECT name FROM sqlite_master WHERE type='index' AND name='uq_competitors_group_own'")).first()
            assert "uq_competitors_platform_offer_id" in str(connection.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name='competitors'")).scalar_one())
            tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
            assert "_alembic_tmp_competitors" not in tables
        engine.dispose()


def test_group_role_migration_allows_only_safe_downgrade_and_round_trip() -> None:
    with TemporaryDirectory() as temporary_directory:
        url = database_url(temporary_directory)
        migrate(url, "20260923_10")
        insert_previous_head_rows(url)
        migrate(url, "20260923_11")
        engine = create_engine(url)
        with engine.begin() as connection:
            connection.execute(text("UPDATE competitors SET group_role = 'own' WHERE id = 1"))
        engine.dispose()

        with pytest.raises(RuntimeError, match="contains own product role data"):
            migrate(url, "20260923_10", downgrade=True)

        engine = create_engine(url)
        with engine.begin() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260923_11"
            assert connection.execute(text("SELECT group_role FROM competitors WHERE id = 1")).scalar_one() == "own"
            assert connection.execute(text("SELECT COUNT(*) FROM product_snapshots")).scalar_one() == 1
            assert connection.execute(text("SELECT name FROM sqlite_master WHERE type='index' AND name='uq_competitors_group_own'")).first()
            tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
            assert "_alembic_tmp_competitors" not in tables
            connection.execute(text("UPDATE competitors SET group_role = 'competitor' WHERE id = 1"))
        engine.dispose()

        migrate(url, "20260923_10", downgrade=True)
        migrate(url, "20260923_11")
        engine = create_engine(url)
        with engine.begin() as connection:
            assert connection.execute(text("SELECT group_role FROM competitors WHERE id = 1")).scalar_one() == "competitor"
            assert connection.execute(text("SELECT COUNT(*) FROM change_events")).scalar_one() == 1
        engine.dispose()
