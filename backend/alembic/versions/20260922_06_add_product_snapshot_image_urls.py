"""add product snapshot image urls

Revision ID: 20260922_06
Revises: 20260922_05
"""

from alembic import op
import sqlalchemy as sa


revision = "20260922_06"
down_revision = "20260922_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "product_snapshots",
        sa.Column("image_urls", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("product_snapshots", "image_urls")
