"""add operating metric observations

Revision ID: 20261010_13
Revises: 20261004_12
"""

from alembic import op
import sqlalchemy as sa


revision = "20261010_13"
down_revision = "20261004_12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "collection_runs",
        sa.Column("operating_metrics_status", sa.String(length=32), server_default="not_attempted", nullable=False),
    )
    with op.batch_alter_table("collection_runs") as batch:
        batch.create_check_constraint(
            "ck_collection_runs_operating_metrics_status",
            "operating_metrics_status IN ('not_attempted', 'success', 'partial', 'no_values', 'failed', 'blocked')",
        )
    op.create_table(
        "operating_metric_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("competitor_id", sa.Integer(), sa.ForeignKey("competitors.id"), nullable=False),
        sa.Column("collection_run_id", sa.Integer(), sa.ForeignKey("collection_runs.id"), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("offer_id", sa.String(length=64), nullable=False),
        sa.Column("metric_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("raw_value", sa.String(length=512), nullable=True),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(length=512), nullable=True),
        sa.CheckConstraint(
            "status IN ('observed', 'placeholder', 'loading', 'source_unavailable', 'read_failed')",
            name="ck_operating_metric_observations_status",
        ),
        sa.CheckConstraint(
            "metric_key IN ('listing_time', 'monthly_deal', 'monthly_dropship', 'annual_units', 'annual_orders', 'review_count', 'positive_rate', 'pickup_rate')",
            name="ck_operating_metric_observations_metric_key",
        ),
        sa.CheckConstraint(
            "(status IN ('observed', 'placeholder') AND raw_value IS NOT NULL AND raw_value != '') OR "
            "(status IN ('loading', 'source_unavailable', 'read_failed') AND raw_value IS NULL)",
            name="ck_operating_metric_observations_raw_value",
        ),
        sa.UniqueConstraint("collection_run_id", "metric_key", name="uq_operating_metric_run_key"),
    )
    op.create_index(
        "ix_operating_metric_competitor_key_time_id",
        "operating_metric_observations",
        ["competitor_id", "metric_key", "observed_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_operating_metric_competitor_key_time_id", table_name="operating_metric_observations")
    op.drop_table("operating_metric_observations")
    with op.batch_alter_table("collection_runs") as batch:
        batch.drop_constraint("ck_collection_runs_operating_metrics_status", type_="check")
        batch.drop_column("operating_metrics_status")
