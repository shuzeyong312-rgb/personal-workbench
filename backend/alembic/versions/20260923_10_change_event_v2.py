"""add ChangeEvent V2 fields and event types

Revision ID: 20260923_10
Revises: 20260922_09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "20260923_10"
down_revision = "20260922_09"
branch_labels = None
depends_on = None


_OLD_CHANGE_TYPES = (
    "'price_increase', 'price_decrease', 'sku_added', 'sku_removed', "
    "'stock_changed', 'title_changed', 'main_image_changed', "
    "'product_offline', 'product_online'"
)
_NEW_CHANGE_TYPES = (
    "'price_increase', 'price_decrease', 'stock_increase', 'stock_decrease', "
    "'sku_added', 'sku_removed', 'sku_sold_out', 'sku_restocked', "
    "'min_order_quantity_increase', 'min_order_quantity_decrease', "
    "'product_offline', 'product_online', 'title_changed', 'main_image_changed', "
    "'stock_changed'"
)
_V2_ONLY_CHANGE_TYPES = (
    "'stock_increase', 'stock_decrease', 'sku_sold_out', 'sku_restocked', "
    "'min_order_quantity_increase', 'min_order_quantity_decrease'"
)


def _set_sqlite_foreign_keys(enabled: bool) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.get_context().autocommit_block():
            bind.exec_driver_sql(f"PRAGMA foreign_keys={'ON' if enabled else 'OFF'}")


def upgrade() -> None:
    _set_sqlite_foreign_keys(False)
    with op.batch_alter_table("change_events", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_change_events_change_type", type_="check")
        batch_op.add_column(sa.Column("collection_run_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("delta_value", sa.Numeric(18, 6), nullable=True))
        batch_op.add_column(sa.Column("delta_rate", sa.Numeric(18, 6), nullable=True))
        batch_op.create_foreign_key(
            "fk_change_events_collection_run_id_collection_runs",
            "collection_runs",
            ["collection_run_id"],
            ["id"],
        )
        batch_op.create_check_constraint(
            "ck_change_events_change_type",
            f"change_type IN ({_NEW_CHANGE_TYPES})",
        )
    _set_sqlite_foreign_keys(True)


def downgrade() -> None:
    has_v2_data = op.get_bind().execute(
        text(
            "SELECT 1 FROM change_events "
            f"WHERE change_type IN ({_V2_ONLY_CHANGE_TYPES}) "
            "OR collection_run_id IS NOT NULL "
            "OR delta_value IS NOT NULL "
            "OR delta_rate IS NOT NULL LIMIT 1"
        )
    ).first()
    if has_v2_data is not None:
        raise RuntimeError(
            "Cannot downgrade 20260923_10: change_events contains V2 event data "
            "or non-NULL V2 fields."
        )

    _set_sqlite_foreign_keys(False)
    with op.batch_alter_table("change_events", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_change_events_change_type", type_="check")
        batch_op.drop_constraint(
            "fk_change_events_collection_run_id_collection_runs",
            type_="foreignkey",
        )
        batch_op.drop_column("collection_run_id")
        batch_op.drop_column("delta_value")
        batch_op.drop_column("delta_rate")
        batch_op.create_check_constraint(
            "ck_change_events_change_type",
            f"change_type IN ({_OLD_CHANGE_TYPES})",
        )
    _set_sqlite_foreign_keys(True)
