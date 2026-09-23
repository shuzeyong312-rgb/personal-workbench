from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

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


def insert_change(database_url: str, change_type: str, snapshot_id: int | None = 1) -> None:
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO change_events (
                        competitor_id, snapshot_id, change_type, entity_key,
                        old_value, new_value, detected_at
                    ) VALUES (1, :snapshot_id, :change_type, NULL, :old_value, :new_value, :detected_at)
                    """
                ),
                {
                    "snapshot_id": snapshot_id,
                    "change_type": change_type,
                    "old_value": "https://img.example.com/a.jpg",
                    "new_value": "https://img.example.com/b.jpg",
                    "detected_at": "2026-09-22 00:00:00",
                },
            )
    finally:
        engine.dispose()


def delete_main_image_changes(database_url: str) -> None:
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM change_events WHERE change_type = 'main_image_changed'")
        )
    engine.dispose()


def insert_lifecycle_change(database_url: str, change_type: str, snapshot_id: int | None) -> None:
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO change_events (
                        competitor_id, snapshot_id, change_type, entity_key,
                        old_value, new_value, detected_at
                    ) VALUES (1, :snapshot_id, :change_type, NULL, :old_value, :new_value, :detected_at)
                    """
                ),
                {
                    "snapshot_id": snapshot_id,
                    "change_type": change_type,
                    "old_value": "active" if change_type == "product_offline" else "offline",
                    "new_value": "offline" if change_type == "product_offline" else "active",
                    "detected_at": "2026-09-22 00:00:00",
                },
            )
    finally:
        engine.dispose()


def insert_collection_run(database_url: str) -> int:
    engine = create_engine(database_url)
    with engine.begin() as connection:
        result = connection.execute(
            text(
                """
                INSERT INTO collection_runs (
                    competitor_id, started_at, finished_at, status, error_type, error_message
                ) VALUES (1, '2026-09-22 01:00:00', '2026-09-22 01:01:00', 'success', NULL, NULL)
                """
            )
        )
        run_id = int(result.lastrowid)
    engine.dispose()
    return run_id


def insert_v2_change(
    database_url: str,
    change_type: str,
    run_id: int,
    *,
    snapshot_id: int | None = 1,
    delta_value: str | None = None,
    delta_rate: str | None = None,
) -> None:
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO change_events (
                    competitor_id, snapshot_id, collection_run_id, change_type, entity_key,
                    old_value, new_value, delta_value, delta_rate, detected_at
                ) VALUES (
                    1, :snapshot_id, :run_id, :change_type, 'sku-1',
                    '10', '20', :delta_value, :delta_rate, '2026-09-22 01:01:00'
                )
                """
            ),
            {
                "snapshot_id": snapshot_id,
                "run_id": run_id,
                "change_type": change_type,
                "delta_value": delta_value,
                "delta_rate": delta_rate,
            },
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


def test_product_lifecycle_migration_allows_nullable_snapshot_and_new_events() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_url = f"sqlite:///{(Path(temporary_directory) / 'migration.db').as_posix()}"
        run_migration(database_url, "20260922_07")
        insert_fixture(database_url)
        run_migration(database_url, "20260922_08")

        insert_lifecycle_change(database_url, "product_offline", None)
        insert_lifecycle_change(database_url, "product_online", 1)

        engine = create_engine(database_url)
        with engine.begin() as connection:
            assert connection.execute(
                text("SELECT snapshot_id, change_type FROM change_events ORDER BY id")
            ).all() == [(None, "product_offline"), (1, "product_online")]
        engine.dispose()


def test_product_lifecycle_downgrade_refuses_lifecycle_rows_without_mutation() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_url = f"sqlite:///{(Path(temporary_directory) / 'migration.db').as_posix()}"
        run_migration(database_url, "20260922_07")
        insert_fixture(database_url)
        run_migration(database_url, "20260922_08")
        insert_lifecycle_change(database_url, "product_offline", None)

        with pytest.raises(RuntimeError, match="product lifecycle events or NULL snapshot_id"):
            run_downgrade(database_url, "20260922_07")

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
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260922_08"
            assert connection.execute(
                text("SELECT snapshot_id, change_type FROM change_events")
            ).all() == [(None, "product_offline")]
        engine.dispose()


def test_product_lifecycle_migration_round_trip_preserves_existing_rows() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_url = f"sqlite:///{(Path(temporary_directory) / 'migration.db').as_posix()}"
        run_migration(database_url, "20260922_07")
        insert_fixture(database_url)
        insert_change(database_url, "title_changed")
        run_migration(database_url, "20260922_08")
        run_downgrade(database_url, "20260922_07")
        run_migration(database_url, "20260922_08")

        engine = create_engine(database_url)
        with engine.begin() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM product_snapshots")).scalar_one() == 1
            assert connection.execute(text("SELECT COUNT(*) FROM change_events")).scalar_one() == 1
        engine.dispose()


def test_product_lifecycle_snapshot_constraint_round_trip_and_rejects_invalid_rows() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_url = f"sqlite:///{(Path(temporary_directory) / 'migration.db').as_posix()}"
        run_migration(database_url, "20260922_07")
        insert_fixture(database_url)
        insert_change(database_url, "title_changed")
        run_migration(database_url, "20260922_08")
        insert_lifecycle_change(database_url, "product_offline", None)
        run_migration(database_url, "20260922_09")

        insert_lifecycle_change(database_url, "product_online", 1)
        insert_change(database_url, "price_increase")

        with pytest.raises(IntegrityError):
            insert_lifecycle_change(database_url, "product_offline", 1)
        with pytest.raises(IntegrityError):
            insert_lifecycle_change(database_url, "product_online", None)
        with pytest.raises(IntegrityError):
            insert_change(database_url, "title_changed", None)

        engine = create_engine(database_url)
        with engine.begin() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260922_09"
            assert connection.execute(text("SELECT COUNT(*) FROM change_events")).scalar_one() == 4
            tables = {
                row[0]
                for row in connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type = 'table'")
                )
            }
            assert "_alembic_tmp_change_events" not in tables
        engine.dispose()

        run_downgrade(database_url, "20260922_08")
        engine = create_engine(database_url)
        with engine.begin() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260922_08"
            assert connection.execute(text("SELECT COUNT(*) FROM change_events")).scalar_one() == 4
            tables = {
                row[0]
                for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))
            }
            assert "_alembic_tmp_change_events" not in tables
        engine.dispose()

        run_migration(database_url, "20260922_09")
        engine = create_engine(database_url)
        with engine.begin() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260922_09"
            assert connection.execute(text("SELECT COUNT(*) FROM change_events")).scalar_one() == 4
        engine.dispose()


def test_change_event_v2_upgrade_preserves_legacy_and_enforces_new_contract() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_url = f"sqlite:///{(Path(temporary_directory) / 'migration.db').as_posix()}"
        run_migration(database_url, "20260922_09")
        insert_fixture(database_url)
        insert_change(database_url, "stock_changed")
        run_migration(database_url, "20260923_10")
        run_id = insert_collection_run(database_url)

        v2_types = [
            "price_increase",
            "price_decrease",
            "stock_increase",
            "stock_decrease",
            "sku_added",
            "sku_removed",
            "sku_sold_out",
            "sku_restocked",
            "min_order_quantity_increase",
            "min_order_quantity_decrease",
            "product_offline",
            "product_online",
            "title_changed",
            "main_image_changed",
        ]
        for change_type in v2_types:
            insert_v2_change(
                database_url,
                change_type,
                run_id,
                snapshot_id=None if change_type == "product_offline" else 1,
                delta_value="10" if change_type == "stock_increase" else None,
                delta_rate="100" if change_type == "stock_increase" else None,
            )

        engine = create_engine(database_url)
        with engine.begin() as connection:
            assert connection.execute(
                text("SELECT collection_run_id, delta_value, delta_rate FROM change_events WHERE change_type = 'stock_changed'")
            ).one() == (None, None, None)
            assert connection.execute(text("SELECT COUNT(*) FROM change_events")).scalar_one() == 15
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "INSERT INTO change_events (competitor_id, snapshot_id, change_type, detected_at) "
                        "VALUES (1, 1, 'not_supported', '2026-09-22 01:00:00')"
                    )
                )
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "INSERT INTO change_events (competitor_id, snapshot_id, collection_run_id, change_type, detected_at) "
                        "VALUES (1, 1, 999, 'price_increase', '2026-09-22 01:00:00')"
                    )
                )
            tables = {
                row[0]
                for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))
            }
            assert "_alembic_tmp_change_events" not in tables
        engine.dispose()


@pytest.mark.parametrize("unsafe_kind", ["v2_event", "delta_value"])
def test_change_event_v2_downgrade_refuses_unsafe_data_without_mutation(unsafe_kind: str) -> None:
    with TemporaryDirectory() as temporary_directory:
        database_url = f"sqlite:///{(Path(temporary_directory) / 'migration.db').as_posix()}"
        run_migration(database_url, "20260922_09")
        insert_fixture(database_url)
        run_migration(database_url, "20260923_10")
        run_id = insert_collection_run(database_url)
        if unsafe_kind == "v2_event":
            insert_v2_change(database_url, "stock_increase", run_id, delta_value="10", delta_rate="100")
        else:
            insert_v2_change(database_url, "stock_changed", run_id, delta_value="10")

        with pytest.raises(RuntimeError, match="contains V2 event data"):
            run_downgrade(database_url, "20260922_09")

        engine = create_engine(database_url)
        with engine.begin() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260923_10"
            assert connection.execute(text("SELECT COUNT(*) FROM change_events")).scalar_one() == 1
            tables = {
                row[0]
                for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))
            }
            assert "_alembic_tmp_change_events" not in tables
        engine.dispose()


def test_change_event_v2_clean_downgrade_upgrade_round_trip() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_url = f"sqlite:///{(Path(temporary_directory) / 'migration.db').as_posix()}"
        run_migration(database_url, "20260922_09")
        insert_fixture(database_url)
        insert_change(database_url, "stock_changed")
        run_migration(database_url, "20260923_10")
        run_downgrade(database_url, "20260922_09")
        run_migration(database_url, "20260923_10")

        engine = create_engine(database_url)
        with engine.begin() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM change_events")).scalar_one() == 1
            assert connection.execute(text("PRAGMA table_info(change_events)")).all()
            tables = {
                row[0]
                for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))
            }
            assert "_alembic_tmp_change_events" not in tables
        engine.dispose()
