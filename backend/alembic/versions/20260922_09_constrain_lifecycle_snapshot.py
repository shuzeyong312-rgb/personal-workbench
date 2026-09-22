"""constrain change event snapshot by type

Revision ID: 20260922_09
Revises: 20260922_08
"""

from alembic import op


revision = "20260922_09"
down_revision = "20260922_08"
branch_labels = None
depends_on = None


_SNAPSHOT_BY_TYPE = (
    "(change_type = 'product_offline' AND snapshot_id IS NULL) OR "
    "(change_type != 'product_offline' AND snapshot_id IS NOT NULL)"
)


def upgrade() -> None:
    with op.batch_alter_table("change_events", recreate="always") as batch_op:
        batch_op.create_check_constraint(
            "ck_change_events_snapshot_by_type",
            _SNAPSHOT_BY_TYPE,
        )


def downgrade() -> None:
    with op.batch_alter_table("change_events", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_change_events_snapshot_by_type", type_="check")
