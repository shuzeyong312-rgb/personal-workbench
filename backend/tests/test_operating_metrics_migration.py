import pytest
from alembic import command
from alembic.config import Config
from alembic.operations import Operations
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine

from app import database


def test_operating_metrics_migration_preserves_old_runs_and_downgrades(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "migration.sqlite"
    monkeypatch.setattr(database, "DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    config = Config("alembic.ini")
    command.upgrade(config, "20261004_12")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO competitors (id, ownership, group_role, platform, offer_id, url, status, is_active, created_at, updated_at) "
            "VALUES (1, 'competitor', 'competitor', '1688', '1081895898799', "
            "'https://detail.1688.com/offer/1081895898799.html', 'active', 1, '2026-10-01', '2026-10-01')"
        ))
        connection.execute(text(
            "INSERT INTO collection_runs (id, competitor_id, started_at, status) VALUES (1, 1, '2026-10-01', 'success')"
        ))
        connection.execute(text(
            "INSERT INTO change_events (id, competitor_id, change_type, detected_at, collection_run_id) "
            "VALUES (1, 1, 'product_offline', '2026-10-01', 1)"
        ))

    command.upgrade(config, "20261010_13")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT operating_metrics_status FROM collection_runs WHERE id=1")).scalar_one() == "not_attempted"
        assert connection.execute(text("SELECT count(*) FROM operating_metric_observations")).scalar_one() == 0
        assert connection.execute(text("SELECT collection_run_id FROM change_events WHERE id=1")).scalar_one() == 1
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    assert {fk["options"].get("ondelete") for fk in inspect(engine).get_foreign_keys("operating_metric_observations")} == {None}

    command.downgrade(config, "20261004_12")
    inspector = inspect(engine)
    assert "operating_metric_observations" not in inspector.get_table_names()
    assert "operating_metrics_status" not in {column["name"] for column in inspector.get_columns("collection_runs")}
    with engine.connect() as connection:
        assert connection.execute(text("SELECT collection_run_id FROM change_events WHERE id=1")).scalar_one() == 1
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []

    foreign_key_pragmas = []

    def record_foreign_key_pragma(_connection, _cursor, statement, _parameters, _context, _executemany) -> None:
        if statement.strip().lower().startswith("pragma foreign_keys="):
            foreign_key_pragmas.append(statement.strip().lower())

    original_create_table = Operations.create_table

    def fail_after_observation_table_create(operations, *args, **kwargs):
        result = original_create_table(operations, *args, **kwargs)
        if args and args[0] == "operating_metric_observations":
            raise RuntimeError("injected failure after observation table create")
        return result

    event.listen(Engine, "before_cursor_execute", record_foreign_key_pragma)
    try:
        with pytest.raises(RuntimeError, match="injected failure after observation table create"):
            with monkeypatch.context() as migration_patch:
                migration_patch.setattr(Operations, "create_table", fail_after_observation_table_create)
                command.upgrade(config, "20261010_13")
    finally:
        event.remove(Engine, "before_cursor_execute", record_foreign_key_pragma)

    assert foreign_key_pragmas[-2:] == ["pragma foreign_keys=off", "pragma foreign_keys=on"]
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20261004_12"
        assert "operating_metrics_status" not in {
            column["name"] for column in inspect(engine).get_columns("collection_runs")
        }
        assert connection.execute(
            text("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='operating_metric_observations'")
        ).scalar_one() == 0
        assert connection.execute(
            text("SELECT count(*) FROM sqlite_master WHERE name LIKE '_alembic_tmp%'")
        ).scalar_one() == 0
        assert connection.execute(text("SELECT collection_run_id FROM change_events WHERE id=1")).scalar_one() == 1
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
        assert connection.execute(text("PRAGMA integrity_check")).scalar_one() == "ok"
    engine.dispose()
