import importlib.util
from pathlib import Path

import pytest


MIGRATION_PATH = Path(__file__).parents[1] / "alembic" / "versions" / "20260920_04_create_competitor_groups.py"


def load_migration():
    spec = importlib.util.spec_from_file_location("competitor_groups_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


class RaisingBatchAlter:
    def __enter__(self):
        raise RuntimeError("batch schema failed")

    def __exit__(self, exc_type, exc_value, traceback):
        return False


def test_upgrade_does_not_restore_foreign_keys_after_schema_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    migration = load_migration()
    foreign_key_changes: list[bool] = []

    monkeypatch.setattr(migration, "_ensure_existing_group_ids_are_null", lambda: None)
    monkeypatch.setattr(
        migration,
        "_set_sqlite_foreign_keys",
        lambda enabled: foreign_key_changes.append(enabled),
    )
    monkeypatch.setattr(migration.op, "create_table", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        migration.op,
        "batch_alter_table",
        lambda *args, **kwargs: RaisingBatchAlter(),
    )

    with pytest.raises(RuntimeError, match="batch schema failed"):
        migration.upgrade()

    assert foreign_key_changes == [False]
