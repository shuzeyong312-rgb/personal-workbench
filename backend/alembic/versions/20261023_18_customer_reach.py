"""Persist one-customer outreach tasks and their human confirmation state."""
from alembic import op
import sqlalchemy as sa

revision = "20261023_18"
down_revision = "20261020_17"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "customer_reach_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("customer_nickname", sa.String(255), nullable=False),
        sa.Column("message_text", sa.String(10000), nullable=False),
        sa.Column("product_url", sa.String(2048), nullable=False),
        sa.Column("content_fingerprint", sa.String(64), nullable=False),
        sa.Column("execution_mode", sa.String(16), nullable=False, server_default="simulated"),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("paused_from_status", sa.String(32)),
        sa.Column("step", sa.String(64), nullable=False),
        sa.Column("matched_customer", sa.String(255)),
        sa.Column("draft_verified", sa.Boolean()),
        sa.Column("send_result", sa.String(32)),
        sa.Column("error_reason", sa.String(1000)),
        sa.Column("screenshot", sa.LargeBinary()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('pending', 'locating', 'preparing', 'awaiting_confirmation', 'sending', 'success', 'failed', 'unknown', 'cancelled', 'paused')",
            name="ck_customer_reach_tasks_status",
        ),
    )
    op.create_index("ix_customer_reach_tasks_created_at", "customer_reach_tasks", ["created_at"])
    op.create_table(
        "customer_reach_campaigns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("customer_category", sa.String(16), nullable=False),
        sa.Column("message_text", sa.String(10000), nullable=False),
        sa.Column("product_url", sa.String(2048), nullable=False),
        sa.Column("content_fingerprint", sa.String(64), nullable=False),
        sa.Column("execution_mode", sa.String(16), nullable=False, server_default="simulated"),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("step", sa.String(64), nullable=False),
        sa.Column("recipients", sa.JSON(), nullable=False),
        sa.Column("current_recipient_id", sa.String(255)),
        sa.Column("screenshot", sa.LargeBinary()),
        sa.Column("error_reason", sa.String(1000)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("customer_category IN ('ordered', 'inquiry')", name="ck_customer_reach_campaigns_category"),
        sa.CheckConstraint(
            "status IN ('pending', 'locating', 'preparing', 'awaiting_confirmation', 'sending', 'success', 'failed', 'unknown', 'cancelled', 'paused')",
            name="ck_customer_reach_campaigns_status",
        ),
    )
    op.create_index("ix_customer_reach_campaigns_created_at", "customer_reach_campaigns", ["created_at"])


def downgrade():
    op.drop_index("ix_customer_reach_campaigns_created_at", table_name="customer_reach_campaigns")
    op.drop_table("customer_reach_campaigns")
    op.drop_index("ix_customer_reach_tasks_created_at", table_name="customer_reach_tasks")
    op.drop_table("customer_reach_tasks")
