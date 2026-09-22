"""allow main image change events

Revision ID: 20260922_07
Revises: 20260922_06
"""

from alembic import op
from sqlalchemy import text


revision = "20260922_07"
down_revision = "20260922_06"
branch_labels = None
depends_on = None


_OLD_CHANGE_TYPES = (
    "'price_increase', 'price_decrease', 'sku_added', 'sku_removed', 'stock_changed', 'title_changed'"
)
_NEW_CHANGE_TYPES = f"{_OLD_CHANGE_TYPES}, 'main_image_changed'"


def upgrade() -> None:
    with op.batch_alter_table("change_events", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_change_events_change_type", type_="check")
        batch_op.create_check_constraint(
            "ck_change_events_change_type",
            f"change_type IN ({_NEW_CHANGE_TYPES})",
        )


def downgrade() -> None:
    has_main_image_changes = op.get_bind().execute(
        text(
            "SELECT 1 FROM change_events "
            "WHERE change_type = 'main_image_changed' LIMIT 1"
        )
    ).first()
    if has_main_image_changes is not None:
        raise RuntimeError(
            "Cannot downgrade 20260922_07: change_events contains "
            "main_image_changed events; remove or explicitly migrate them "
            "before retrying."
        )

    with op.batch_alter_table("change_events", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_change_events_change_type", type_="check")
        batch_op.create_check_constraint(
            "ck_change_events_change_type",
            f"change_type IN ({_OLD_CHANGE_TYPES})",
        )
