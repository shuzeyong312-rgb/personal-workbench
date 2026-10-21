"""Exact manufacturer/model/name identity; no product or receipt rewrites."""
from alembic import op
import sqlalchemy as sa

revision = "20261020_17"
down_revision = "20261018_16"
branch_labels = None
depends_on = None
OLD = "uq_library_products_manufacturer_model"
NEW = "uq_library_products_manufacturer_model_name"


def transaction():
    bind = op.get_bind()
    # SQLite legacy driver mode does not BEGIN for DDL; include Alembic's stamp.
    if not bind.connection.driver_connection.in_transaction:
        bind.exec_driver_sql("BEGIN IMMEDIATE")
    if bind.exec_driver_sql("PRAGMA integrity_check").scalar() != "ok" or bind.exec_driver_sql("PRAGMA foreign_key_check").all():
        raise RuntimeError("Database integrity check failed; migration refused")
    return bind


def upgrade():
    bind = transaction()
    for manufacturer, model, name in bind.execute(sa.text("SELECT manufacturer_name, model, name FROM library_products")):
        if (not isinstance(manufacturer, str) or not manufacturer or len(manufacturer) > 200 or manufacturer != " ".join(manufacturer.split())
            or not isinstance(name, str) or not name or len(name) > 200 or name != name.replace("\r\n", "\n").replace("\r", "\n").strip()
            or model is not None and (not isinstance(model, str) or not model or len(model) > 200 or model != model.replace("\r\n", "\n").replace("\r", "\n").strip())):
            raise RuntimeError("Noncanonical product identity; review data before migration")
    if bind.execute(sa.text("SELECT 1 FROM library_products GROUP BY manufacturer_name, model, name HAVING count(*) > 1 LIMIT 1")).first():
        raise RuntimeError("Exact duplicate product identity; review data before migration")
    op.create_index(NEW, "library_products", ["manufacturer_name", "model", "name"], unique=True, sqlite_where=sa.text("model IS NOT NULL"))
    op.drop_index(OLD, table_name="library_products")


def downgrade():
    bind = transaction()
    if bind.execute(sa.text("SELECT 1 FROM library_products WHERE model IS NOT NULL GROUP BY manufacturer_name, model HAVING count(*) > 1 LIMIT 1")).first():
        raise RuntimeError("Unsafe downgrade: same-model independent products exist; export new data and restore a verified pre-upgrade backup")
    op.create_index(OLD, "library_products", ["manufacturer_name", "model"], unique=True, sqlite_where=sa.text("model IS NOT NULL"))
    op.drop_index(NEW, table_name="library_products")
