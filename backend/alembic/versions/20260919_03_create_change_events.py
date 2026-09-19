"""create change events

Revision ID: 20260919_03
Revises: 20260919_02
"""

from alembic import op
import sqlalchemy as sa


revision = "20260919_03"
down_revision = "20260919_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "change_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("competitor_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("change_type", sa.String(length=64), nullable=False),
        sa.Column("entity_key", sa.String(length=128), nullable=True),
        sa.Column("old_value", sa.String(length=512), nullable=True),
        sa.Column("new_value", sa.String(length=512), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["competitor_id"], ["competitors.id"]),
        sa.ForeignKeyConstraint(["snapshot_id"], ["product_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "change_type IN ('price_increase', 'price_decrease', 'sku_added', 'sku_removed', 'stock_changed', 'title_changed')",
            name="ck_change_events_change_type",
        ),
    )
    op.create_index(
        "ix_change_events_competitor_detected_at_id",
        "change_events",
        ["competitor_id", "detected_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_change_events_competitor_detected_at_id", table_name="change_events")
    op.drop_table("change_events")
