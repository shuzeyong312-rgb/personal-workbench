"""add product lifecycle events

Revision ID: 20260922_08
Revises: 20260922_07
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "20260922_08"
down_revision = "20260922_07"
branch_labels = None
depends_on = None


_OLD_CHANGE_TYPES = (
    "'price_increase', 'price_decrease', 'sku_added', 'sku_removed', "
    "'stock_changed', 'title_changed', 'main_image_changed'"
)
_NEW_CHANGE_TYPES = f"{_OLD_CHANGE_TYPES}, 'product_offline', 'product_online'"


def upgrade() -> None:
    with op.batch_alter_table("change_events", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_change_events_change_type", type_="check")
        batch_op.alter_column(
            "snapshot_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
        batch_op.create_check_constraint(
            "ck_change_events_change_type",
            f"change_type IN ({_NEW_CHANGE_TYPES})",
        )


def downgrade() -> None:
    has_lifecycle_data = op.get_bind().execute(
        text(
            "SELECT 1 FROM change_events "
            "WHERE change_type IN ('product_offline', 'product_online') "
            "OR snapshot_id IS NULL LIMIT 1"
        )
    ).first()
    if has_lifecycle_data is not None:
        raise RuntimeError(
            "Cannot downgrade 20260922_08: change_events contains "
            "product lifecycle events or NULL snapshot_id."
        )

    with op.batch_alter_table("change_events", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_change_events_change_type", type_="check")
        batch_op.alter_column(
            "snapshot_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.create_check_constraint(
            "ck_change_events_change_type",
            f"change_type IN ({_OLD_CHANGE_TYPES})",
        )
