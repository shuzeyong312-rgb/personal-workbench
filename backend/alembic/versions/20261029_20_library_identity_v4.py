"""Global exact product identity; refuse ambiguous historical records."""
from alembic import op
import sqlalchemy as sa

revision = "20261029_20"
down_revision = "20261027_19"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    # Include preflight, DDL and Alembic's revision stamp in one SQLite write lock.
    if not bind.connection.driver_connection.in_transaction:
        bind.exec_driver_sql("BEGIN IMMEDIATE")
    if bind.exec_driver_sql("PRAGMA integrity_check").scalar() != "ok" or bind.exec_driver_sql("PRAGMA foreign_key_check").all():
        raise RuntimeError("Database integrity check failed; migration refused")
    rows = bind.execute(sa.text("SELECT id, manufacturer_name, model, name FROM library_products ORDER BY id")).mappings().all()
    groups = {}
    for row in rows:
        for field in ("model", "name"):
            value = row[field]
            if field == "model" and value is None:
                continue
            if not isinstance(value, str) or not value or len(value) > 200 or value != value.replace("\r\n", "\n").replace("\r", "\n").strip():
                raise RuntimeError(f"Noncanonical product identity: id={row['id']}; migration refused")
        groups.setdefault((row['model'], row['name']), []).append(dict(row))
    conflicts = [group for group in groups.values() if len(group) > 1]
    if conflicts:
        raise RuntimeError(f"Product identity conflicts; no automatic merge: {conflicts!r}")
    op.create_index("uq_library_products_model_name", "library_products", ["model", "name"], unique=True, sqlite_where=sa.text("model IS NOT NULL"))
    op.create_index("uq_library_products_null_model_name", "library_products", ["name"], unique=True, sqlite_where=sa.text("model IS NULL"))
    op.drop_index("uq_library_products_manufacturer_model_name", table_name="library_products")


def downgrade():
    raise RuntimeError("Unsafe downgrade: stop writes, export incremental data and restore a verified pre-upgrade backup")
