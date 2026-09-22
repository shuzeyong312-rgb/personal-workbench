"""add product minimum order quantity

Revision ID: 20260922_05
Revises: 20260920_04
"""

from alembic import op
import sqlalchemy as sa


revision = "20260922_05"
down_revision = "20260920_04"
branch_labels = None
depends_on = None


def _set_sqlite_foreign_keys(enabled: bool) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.get_context().autocommit_block():
            bind.exec_driver_sql(f"PRAGMA foreign_keys={'ON' if enabled else 'OFF'}")


def upgrade() -> None:
    _set_sqlite_foreign_keys(False)
    with op.batch_alter_table("product_snapshots", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("min_order_quantity", sa.Integer(), nullable=True))
        batch_op.create_check_constraint(
            "ck_product_snapshots_min_order_quantity",
            "min_order_quantity IS NULL OR min_order_quantity >= 1",
        )
    _set_sqlite_foreign_keys(True)


def downgrade() -> None:
    _set_sqlite_foreign_keys(False)
    with op.batch_alter_table("product_snapshots", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_product_snapshots_min_order_quantity", type_="check")
        batch_op.drop_column("min_order_quantity")
    _set_sqlite_foreign_keys(True)
