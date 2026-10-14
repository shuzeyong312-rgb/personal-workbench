"""Scoped SQLite status-constraint repair candidate; dry-run unless --apply is explicit."""
import argparse
from contextlib import closing
import hashlib
import re
import sqlite3
from pathlib import Path


VALID = ("unknown", "active", "offline")
CONSTRAINT = "ck_competitors_status"
TEMP = "_repair_competitors_status"


def status_check_exists(sql: str) -> bool:
    # Compare the expression and values, independent of CHECK naming and IN order.
    matches = re.findall(r'CHECK\s*\(\s*[\("`\[]*status[\)"`\]]*\s+IN\s*\(([^()]*)\)\s*\)', sql, re.I)
    return any(set(re.findall(r"'([^']*)'", value)) == set(VALID)
               and re.fullmatch(r"\s*'[^']*'\s*(?:,\s*'[^']*'\s*){2}", value) for value in matches)


def facts(db: sqlite3.Connection) -> dict:
    tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {table: hashlib.sha256(repr(sorted(db.execute('SELECT * FROM "' + table.replace('"', '""') + '"').fetchall(), key=repr)).encode()).hexdigest() for table in tables}


def repair_database(path: Path, *, apply: bool = False, backup_path: Path | None = None) -> dict:
    path = path.resolve(strict=True)
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as source:
        sql = source.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='competitors'").fetchone()
        if not sql:
            raise RuntimeError('BLOCKED: competitors table is missing')
        sql = sql[0]
        invalid = source.execute("SELECT id, status FROM competitors WHERE status IS NULL OR status NOT IN (?,?,?)", VALID).fetchall()
        if invalid:
            raise RuntimeError(f'BLOCKED: invalid status rows {invalid}')
        if status_check_exists(sql):
            return {'changed': False, 'reason': 'equivalent status CHECK already exists'}
        if re.search(r'\bCONSTRAINT\s+["`\[]?ck_competitors_status\b', sql, re.I):
            raise RuntimeError('BLOCKED: named status constraint has a different expression')
        if source.execute("SELECT 1 FROM sqlite_master WHERE name=?", (TEMP,)).fetchone():
            raise RuntimeError('BLOCKED: repair temporary table already exists')
        if not re.match(r'^CREATE\s+TABLE\s+(?:"competitors"|`competitors`|\[competitors\]|competitors)\s*\(', sql, re.I):
            raise RuntimeError('BLOCKED: unexpected CREATE TABLE form')
        if source.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or source.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('BLOCKED: integrity or foreign keys failed')
        before = facts(source)
        objects = source.execute("SELECT type,name,sql FROM sqlite_master WHERE tbl_name='competitors' AND type IN ('index','trigger') AND sql IS NOT NULL ORDER BY type,name").fetchall()
        if not apply:
            return {'changed': False, 'reason': 'status CHECK missing; repair requires explicit apply', 'objects_to_preserve': len(objects)}
        if backup_path is None:
            raise RuntimeError('BLOCKED: explicit new backup path required')
        backup_path = backup_path.resolve()
        if backup_path.exists() or backup_path == path:
            raise RuntimeError('BLOCKED: backup must be a new distinct file')
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(backup_path)) as destination:
            source.backup(destination)
            if (facts(destination) != before
                    or destination.execute('PRAGMA integrity_check').fetchall() != [('ok',)]
                    or destination.execute('PRAGMA foreign_key_check').fetchall()):
                raise RuntimeError('BLOCKED: backup data differs')
    db = sqlite3.connect(path, isolation_level=None)
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA foreign_keys=OFF')
        db.execute('BEGIN IMMEDIATE')
        if facts(db) != before or db.execute("SELECT sql FROM sqlite_master WHERE name='competitors'").fetchone()[0] != sql:
            raise RuntimeError('BLOCKED: database changed after backup')
        changed_sql = re.sub(r'^(CREATE\s+TABLE\s+)(?:"competitors"|`competitors`|\[competitors\]|competitors)', r'\1"' + TEMP + '"', sql, count=1, flags=re.I)
        end = changed_sql.rfind(')')
        changed_sql = changed_sql[:end] + ", CONSTRAINT " + CONSTRAINT + " CHECK (status IN ('unknown', 'active', 'offline'))" + changed_sql[end:]
        db.execute(changed_sql)
        columns = [row[1] for row in db.execute('PRAGMA table_info(competitors)')]
        quoted = ','.join('"' + column.replace('"','""') + '"' for column in columns)
        db.execute(f'INSERT INTO "{TEMP}" ({quoted}) SELECT {quoted} FROM competitors')
        db.execute('DROP TABLE competitors')
        db.execute(f'ALTER TABLE "{TEMP}" RENAME TO competitors')
        for _, _, statement in objects:
            db.execute(statement)
        if facts(db) != before or db.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or db.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('BLOCKED: rebuilt schema or records failed validation')
        after_objects = db.execute("SELECT type,name,sql FROM sqlite_master WHERE tbl_name='competitors' AND type IN ('index','trigger') AND sql IS NOT NULL ORDER BY type,name").fetchall()
        if after_objects != objects:
            raise RuntimeError('BLOCKED: indexes or triggers changed')
        db.execute('COMMIT')
        return {'changed': True, 'backup': str(backup_path), 'all_table_data_unchanged': True}
    except BaseException:
        if db.in_transaction:
            db.execute('ROLLBACK')
        raise
    finally:
        try:
            db.execute('PRAGMA foreign_keys=ON')
        finally:
            db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup', type=Path)
    args = parser.parse_args()
    print(repair_database(args.database, apply=args.apply, backup_path=args.backup))
