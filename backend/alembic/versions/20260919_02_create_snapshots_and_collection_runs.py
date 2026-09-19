"""create snapshots and collection runs

Revision ID: 20260919_02
Revises: 20260919_01
"""

from alembic import op
import sqlalchemy as sa


revision = "20260919_02"
down_revision = "20260919_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("competitor_id", sa.Integer(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("shop_name", sa.String(length=255), nullable=False),
        sa.Column("main_image_url", sa.String(length=1024), nullable=True),
        sa.Column("price_min", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("price_max", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("product_status", sa.String(length=32), nullable=False),
        sa.Column("collection_source", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["competitor_id"], ["competitors.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "product_status IN ('unknown', 'active', 'offline')",
            name="ck_product_snapshots_product_status",
        ),
        sa.CheckConstraint(
            "collection_source IN ('html', 'network', 'mixed')",
            name="ck_product_snapshots_collection_source",
        ),
    )
    op.create_table(
        "sku_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("sku_id", sa.String(length=128), nullable=False),
        sa.Column("sku_name", sa.String(length=512), nullable=False),
        sa.Column("stock", sa.Integer(), nullable=True),
        sa.Column("price", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.ForeignKeyConstraint(
            ["product_snapshot_id"], ["product_snapshots.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "collection_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("competitor_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_type", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=2048), nullable=True),
        sa.ForeignKeyConstraint(["competitor_id"], ["competitors.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('running', 'success', 'failed')",
            name="ck_collection_runs_status",
        ),
    )


def downgrade() -> None:
    op.drop_table("collection_runs")
    op.drop_table("sku_snapshots")
    op.drop_table("product_snapshots")
