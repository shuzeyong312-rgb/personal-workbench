"""Read-only source backup and isolated identity V2 migration rehearsal.

Run from backend: python -m scripts.rehearse_library_identity_v2 --source PATH --output NEW_DIRECTORY
Never upgrades the source, never overwrites an existing output directory.
"""
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from app import database

OLD = "20261018_16"
NEW = "20261020_17"


def connect_readonly(path):
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def backup(source, target):
    if target.exists():
        raise RuntimeError("Backup destination exists")
    with connect_readonly(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)


def facts(path):
    with connect_readonly(path) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)] or db.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Integrity check failed")
        tables = {}
        for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'alembic_version' ORDER BY name"):
            quoted = '"' + name.replace('"', '""') + '"'
            rows = db.execute(f"SELECT * FROM {quoted}").fetchall()
            encoded = sorted(json.dumps(row, ensure_ascii=False, default=str) for row in rows)
            tables[name] = {"count": len(rows), "sha256": hashlib.sha256(json.dumps(encoded, ensure_ascii=False).encode()).hexdigest()}
        return {"revision": db.execute("SELECT version_num FROM alembic_version").fetchone()[0], "integrity": "ok", "foreign_key_violations": 0, "tables": tables, "indexes": db.execute("SELECT name,sql FROM sqlite_master WHERE type='index' AND tbl_name='library_products' ORDER BY name").fetchall()}


def migrate(path, revision, downgrade=False):
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
    original = database.DATABASE_URL
    database.DATABASE_URL = f"sqlite:///{path.resolve().as_posix()}"
    try:
        (command.downgrade if downgrade else command.upgrade)(config, revision)
    finally:
        database.DATABASE_URL = original


def rehearse(source, output):
    output.mkdir(parents=True, exist_ok=False)
    original = output / "before.db"
    migrated = output / "migrated.db"
    backup(source, original)
    before = facts(original)
    if before["revision"] != OLD:
        raise RuntimeError("Expected reviewed source revision " + OLD)
    backup(original, migrated)
    migrate(migrated, NEW)
    after = facts(migrated)
    if before["tables"] != after["tables"] or after["revision"] != NEW:
        raise RuntimeError("Data changed during migration")
    # All mutations below are confined to disposable copies of the migrated DB.
    check = output / "write-check.db"
    backup(migrated, check)
    with sqlite3.connect(check) as db:
        sql = "INSERT INTO library_products(manufacturer_name,model,name,created_at,updated_at,version) VALUES ('__identity_v2_rehearsal__','same-model',?,'2026-10-20','2026-10-20',1)"
        db.execute(sql, ("A",)); db.execute(sql, ("B",))
        try:
            db.execute(sql, ("A",))
        except sqlite3.IntegrityError:
            pass
        else:
            raise RuntimeError("Exact uniqueness failed")
    try:
        migrate(check, OLD, downgrade=True)
    except RuntimeError as exc:
        if "Unsafe downgrade" not in str(exc):
            raise
    else:
        raise RuntimeError("Unsafe downgrade was allowed")
    if facts(check)["revision"] != NEW:
        raise RuntimeError("Rejected downgrade changed revision")
    migrate(migrated, OLD, downgrade=True)
    if facts(migrated)["tables"] != before["tables"]:
        raise RuntimeError("Compatible downgrade changed data")
    migrate(migrated, NEW)
    restored = output / "restored.db"
    backup(original, restored)
    if facts(restored) != before:
        raise RuntimeError("Backup restoration mismatch")
    report = {"source": str(source.resolve()), "backup": str(original.resolve()), "backup_sha256": hashlib.sha256(original.read_bytes()).hexdigest(), "before": before, "after": after, "all_tables_unchanged": True, "independent_same_model_insert": "PASS", "exact_duplicate_blocked": "PASS", "unsafe_downgrade_blocked": "PASS", "compatible_roundtrip": "PASS", "backup_restore": "PASS", "production_migrated": False}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = rehearse(args.source, args.output)
    print(json.dumps({"report": str(args.output / "report.json"), "all_tables_unchanged": result["all_tables_unchanged"], "products": result["before"]["tables"]["library_products"]["count"], "production_migrated": False}))
