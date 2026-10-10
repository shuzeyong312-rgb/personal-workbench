from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

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

    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT operating_metrics_status FROM collection_runs WHERE id=1")).scalar_one() == "not_attempted"
        assert connection.execute(text("SELECT count(*) FROM operating_metric_observations")).scalar_one() == 0
    assert {fk["options"].get("ondelete") for fk in inspect(engine).get_foreign_keys("operating_metric_observations")} == {None}

    command.downgrade(config, "20261004_12")
    inspector = inspect(engine)
    assert "operating_metric_observations" not in inspector.get_table_names()
    assert "operating_metrics_status" not in {column["name"] for column in inspector.get_columns("collection_runs")}
    engine.dispose()
