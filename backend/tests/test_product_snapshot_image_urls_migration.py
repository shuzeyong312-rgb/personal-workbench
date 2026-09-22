from pathlib import Path
from tempfile import TemporaryDirectory

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

import app.database as database


BACKEND_ROOT = Path(__file__).parents[1]


def run_revision(database_url: str, revision: str) -> None:
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


def test_product_snapshot_image_urls_migration_round_trip_preserves_existing_rows() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "migration.db"
        database_url = f"sqlite:///{database_path.as_posix()}"
        run_revision(database_url, "20260922_05")

        engine = create_engine(database_url)
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO competitors (
                        platform, offer_id, url, title, shop_name, main_image_url,
                        status, is_active, created_at, updated_at, last_collected_at
                    ) VALUES (
                        '1688', 'migration-offer', 'https://example.com/offer',
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

        run_revision(database_url, "20260922_06")
        assert "image_urls" in {column["name"] for column in inspect(engine).get_columns("product_snapshots")}
        with engine.begin() as connection:
            assert connection.execute(
                text("SELECT title, image_urls FROM product_snapshots WHERE id = 1")
            ).one() == ("历史商品", None)
            connection.execute(
                text("UPDATE product_snapshots SET image_urls = :image_urls WHERE id = 1"),
                {"image_urls": '["https://example.com/main.jpg"]'},
            )

        run_downgrade(database_url, "20260922_05")
        assert "image_urls" not in {column["name"] for column in inspect(engine).get_columns("product_snapshots")}
        with engine.begin() as connection:
            assert connection.execute(
                text("SELECT title FROM product_snapshots WHERE id = 1")
            ).scalar_one() == "历史商品"

        run_revision(database_url, "20260922_06")
        assert "image_urls" in {column["name"] for column in inspect(engine).get_columns("product_snapshots")}
        with engine.begin() as connection:
            assert connection.execute(
                text("SELECT title, image_urls FROM product_snapshots WHERE id = 1")
            ).one() == ("历史商品", None)
        engine.dispose()
