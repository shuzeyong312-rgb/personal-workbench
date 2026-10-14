"""persist collection batches and attempt navigation facts

Revision ID: 20261012_14
Revises: 20261010_13
"""

from alembic import op
import sqlalchemy as sa


revision = "20261012_14"
down_revision = "20261010_13"
branch_labels = None
depends_on = None


def _set_sqlite_foreign_keys(enabled: bool) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.get_context().autocommit_block():
            bind.exec_driver_sql(f"PRAGMA foreign_keys={'ON' if enabled else 'OFF'}")
        if not enabled:
            bind.exec_driver_sql("BEGIN")


def upgrade() -> None:
    op.create_table(
        "collection_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.String(36), nullable=False),
        sa.Column("trigger_kind", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("lifecycle_status", sa.String(16), nullable=False),
        sa.Column("outcome_code", sa.String(32)),
        sa.Column("settings_snapshot", sa.JSON(), nullable=False),
        sa.Column("planned_products", sa.Integer(), nullable=False),
        sa.Column("scheduler_occurrence_key", sa.String(512)),
        sa.Column("protection_reason", sa.String(128)),
        sa.Column("protection_details", sa.String(512)),
        sa.Column("circuit_breaker_streak", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("circuit_breaker_cancelled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("security_error_summary", sa.String(512)),
        sa.CheckConstraint("trigger_kind IN ('manual_selected', 'manual_all_active', 'scheduled')", name="ck_collection_batches_trigger_kind"),
        sa.CheckConstraint("lifecycle_status IN ('created', 'running', 'terminal')", name="ck_collection_batches_lifecycle"),
        sa.CheckConstraint("outcome_code IS NULL OR outcome_code IN ('success', 'partial_success', 'partial_failure', 'user_ended', 'verification_required', 'collect_failed', 'infrastructure_error', 'interrupted')", name="ck_collection_batches_outcome"),
        sa.CheckConstraint("planned_products >= 0", name="ck_collection_batches_planned_products"),
        sa.UniqueConstraint("task_id", name="uq_collection_batches_task_id"),
        sa.UniqueConstraint("scheduler_occurrence_key", name="uq_collection_batches_scheduler_occurrence"),
    )
    op.create_index("ix_collection_batches_started_at_id", "collection_batches", ["started_at", "id"])
    op.create_table(
        "collection_batch_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("collection_batches.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("competitor_id", sa.Integer(), sa.ForeignKey("competitors.id"), nullable=True),
        sa.Column("execution_status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("final_result", sa.String(32)),
        sa.Column("base_result", sa.String(16)),
        sa.Column("operating_metrics_status", sa.String(32)),
        sa.Column("protection_reason", sa.String(128)),
        sa.Column("attempts_started", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("page_visits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("page_visits_unknown", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("verification_resume_visits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_visits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("technical_exception_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("placeholder_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_unavailable_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("loading_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("read_failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancelled_retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stop_reason", sa.String(128)),
        sa.CheckConstraint("execution_status IN ('queued', 'running', 'completed', 'failed', 'not_executed')", name="ck_collection_batch_items_execution_status"),
        sa.CheckConstraint("final_result IS NULL OR final_result IN ('first_pass_success', 'verification_resume_success', 'retry_success', 'final_failed', 'verification_required', 'not_executed')", name="ck_collection_batch_items_final_result"),
        sa.CheckConstraint("base_result IS NULL OR base_result IN ('success', 'failed', 'not_attempted')", name="ck_collection_batch_items_base_result"),
        sa.CheckConstraint("attempts_started >= 0 AND page_visits >= 0 AND page_visits_unknown >= 0 AND verification_resume_visits >= 0 AND retry_visits >= 0 AND placeholder_count >= 0 AND source_unavailable_count >= 0 AND loading_count >= 0 AND read_failed_count >= 0", name="ck_collection_batch_items_counts"),
        sa.UniqueConstraint("batch_id", "position", name="uq_collection_batch_items_position"),
        sa.UniqueConstraint("batch_id", "competitor_id", name="uq_collection_batch_items_competitor"),
    )
    op.create_index("ix_collection_batch_items_batch_status", "collection_batch_items", ["batch_id", "execution_status", "final_result"])
    _set_sqlite_foreign_keys(False)
    try:
        with op.batch_alter_table("collection_runs") as batch:
            batch.add_column(sa.Column("collection_batch_item_id", sa.Integer(), sa.ForeignKey("collection_batch_items.id", name="fk_collection_runs_batch_item"), nullable=True))
            batch.add_column(sa.Column("attempt_number", sa.Integer(), nullable=True))
            batch.add_column(sa.Column("attempt_kind", sa.String(32), nullable=True))
            batch.add_column(sa.Column("navigation_claimed_at", sa.DateTime(timezone=True), nullable=True))
            batch.add_column(sa.Column("navigation_confirmed_at", sa.DateTime(timezone=True), nullable=True))
            batch.add_column(sa.Column("navigation_terminal_reason", sa.String(64), nullable=True))
            batch.create_check_constraint(
                "ck_collection_runs_attempt_kind",
                "attempt_kind IS NULL OR attempt_kind IN ('first_pass', 'verification_resume', 'operating_metrics_retry')",
            )
            batch.create_unique_constraint("uq_collection_runs_item_attempt", ["collection_batch_item_id", "attempt_number"])
    finally:
        _set_sqlite_foreign_keys(True)


def downgrade() -> None:
    _set_sqlite_foreign_keys(False)
    try:
        with op.batch_alter_table("collection_runs") as batch:
            batch.drop_constraint("uq_collection_runs_item_attempt", type_="unique")
            batch.drop_constraint("ck_collection_runs_attempt_kind", type_="check")
            batch.drop_column("navigation_terminal_reason")
            batch.drop_column("navigation_confirmed_at")
            batch.drop_column("navigation_claimed_at")
            batch.drop_column("attempt_kind")
            batch.drop_column("attempt_number")
            batch.drop_column("collection_batch_item_id")
    finally:
        _set_sqlite_foreign_keys(True)
    op.drop_index("ix_collection_batch_items_batch_status", table_name="collection_batch_items")
    op.drop_table("collection_batch_items")
    op.drop_index("ix_collection_batches_started_at_id", table_name="collection_batches")
    op.drop_table("collection_batches")
