from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

import app.database as database


BACKEND_ROOT = Path(__file__).parents[1]


def run_migration(database_url: str, revision: str) -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    original_database_url = database.DATABASE_URL
    database.DATABASE_URL = database_url
    try:
        command.upgrade(config, revision)
    finally:
        database.DATABASE_URL = original_database_url


def run_downgrade(database_url: str, revision: str) -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    original_database_url = database.DATABASE_URL
    database.DATABASE_URL = database_url
    try:
        command.downgrade(config, revision)
    finally:
        database.DATABASE_URL = original_database_url


def insert_fixture(database_url: str) -> None:
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO competitors (
                    platform, offer_id, url, title, shop_name, main_image_url,
                    status, is_active, created_at, updated_at, last_collected_at
                ) VALUES (
                    '1688', 'migration-offer', 'https://detail.1688.com/offer/migration',
                    '历史商品', '历史店铺', NULL, 'unknown', 1,
                    '2026-09-22 00:00:00', '2026-09-22 00:00:00', NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO product_snapshots (
                    competitor_id, captured_at, title, shop_name, main_image_url,
                    price_min, price_max, min_order_quantity, product_status, collection_source
                ) VALUES (
                    1, '2026-09-22 00:00:00', '历史商品', '历史店铺', NULL,
                    NULL, NULL, NULL, 'unknown', 'html'
                )
                """
            )
        )
    engine.dispose()


def insert_change(database_url: str, change_type: str) -> None:
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO change_events (
                    competitor_id, snapshot_id, change_type, entity_key,
                    old_value, new_value, detected_at
                ) VALUES (1, 1, :change_type, NULL, :old_value, :new_value, :detected_at)
                """
            ),
            {
                "change_type": change_type,
                "old_value": "https://img.example.com/a.jpg",
                "new_value": "https://img.example.com/b.jpg",
                "detected_at": "2026-09-22 00:00:00",
            },
        )
    engine.dispose()


def delete_main_image_changes(database_url: str) -> None:
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM change_events WHERE change_type = 'main_image_changed'")
        )
    engine.dispose()


def test_downgrade_refuses_existing_main_image_changes_without_mutation() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_url = f"sqlite:///{(Path(temporary_directory) / 'migration.db').as_posix()}"
        run_migration(database_url, "20260922_06")
        insert_fixture(database_url)
        insert_change(database_url, "title_changed")
        run_migration(database_url, "20260922_07")
        insert_change(database_url, "main_image_changed")

        errors = []
        for _ in range(2):
            with pytest.raises(RuntimeError, match="contains main_image_changed events") as exc_info:
                run_downgrade(database_url, "20260922_06")
            errors.append(str(exc_info.value))

            engine = create_engine(database_url)
            with engine.begin() as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        text("SELECT name FROM sqlite_master WHERE type = 'table'")
                    )
                }
                assert "change_events" in tables
                assert "_alembic_tmp_change_events" not in tables
                assert connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one() == "20260922_07"
                assert connection.execute(
                    text(
                        "SELECT change_type, old_value, new_value "
                        "FROM change_events ORDER BY id"
                    )
                ).all() == [
                    ("title_changed", "https://img.example.com/a.jpg", "https://img.example.com/b.jpg"),
                    ("main_image_changed", "https://img.example.com/a.jpg", "https://img.example.com/b.jpg"),
                ]
            engine.dispose()

        assert errors[0] == errors[1]


def test_main_image_change_migration_round_trip_preserves_rows() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_url = f"sqlite:///{(Path(temporary_directory) / 'migration.db').as_posix()}"
        run_migration(database_url, "20260922_06")
        insert_fixture(database_url)
        insert_change(database_url, "title_changed")

        run_migration(database_url, "20260922_07")
        insert_change(database_url, "main_image_changed")
        delete_main_image_changes(database_url)
        run_downgrade(database_url, "20260922_06")

        run_migration(database_url, "20260922_07")
        insert_change(database_url, "main_image_changed")

        engine = create_engine(database_url)
        with engine.begin() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM product_snapshots")).scalar_one() == 1
            assert connection.execute(text("SELECT COUNT(*) FROM change_events")).scalar_one() == 2
        engine.dispose()
