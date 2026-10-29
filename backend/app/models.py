from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, JSON, Numeric, String, UniqueConstraint, event, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CompetitorGroup(Base):
    __tablename__ = "competitor_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Competitor(Base):
    __tablename__ = "competitors"
    __table_args__ = (
        UniqueConstraint("platform", "offer_id", name="uq_competitors_platform_offer_id"),
        CheckConstraint("status IN ('unknown', 'active', 'offline')", name="ck_competitors_status"),
        CheckConstraint("group_role IN ('competitor', 'own')", name="ck_competitors_group_role"),
        CheckConstraint("ownership IN ('self', 'competitor')", name="ck_competitors_ownership"),
        CheckConstraint(
            "(ownership = 'competitor' AND group_role = 'competitor') OR "
            "(ownership = 'self' AND ((group_id IS NULL AND group_role = 'competitor') OR "
            "(group_id IS NOT NULL AND group_role = 'own')))" ,
            name="ck_competitors_ownership_role",
        ),
        Index(
            "uq_competitors_group_own",
            "group_id",
            unique=True,
            sqlite_where=text("group_role = 'own'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int | None] = mapped_column(
        ForeignKey("competitor_groups.id", name="fk_competitors_group_id_competitor_groups"), nullable=True
    )
    ownership: Mapped[str] = mapped_column(String(16), nullable=False, default="competitor", server_default="competitor")
    group_role: Mapped[str] = mapped_column(String(16), nullable=False, default="competitor", server_default="competitor")
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    offer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    shop_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    main_image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


@event.listens_for(Competitor, "before_insert")
def _preserve_legacy_own_fixture_state(_mapper, _connection, target: Competitor) -> None:
    # Existing ORM callers that still construct the pre-ownership own role are
    # upgraded to the equivalent ownership fact before the database constraint runs.
    if target.group_role == "own" and target.ownership != "self":
        target.ownership = "self"


@event.listens_for(Competitor, "before_update")
def _preserve_legacy_own_update_state(_mapper, _connection, target: Competitor) -> None:
    # Keep pre-ownership ORM fixtures valid while all product-facing write
    # paths continue to derive group_role from ownership explicitly.
    if target.group_role == "own" and target.ownership != "self":
        target.ownership = "self"


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(String(255), nullable=True)


class CustomerReachTask(Base):
    __tablename__ = "customer_reach_tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'locating', 'preparing', 'awaiting_confirmation', 'sending', 'success', 'failed', 'unknown', 'cancelled', 'paused')",
            name="ck_customer_reach_tasks_status",
        ),
        Index("ix_customer_reach_tasks_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    customer_nickname: Mapped[str] = mapped_column(String(255), nullable=False)
    message_text: Mapped[str] = mapped_column(String(10000), nullable=False)
    product_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="simulated")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    paused_from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    step: Mapped[str] = mapped_column(String(64), nullable=False, default="等待执行")
    matched_customer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    draft_verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    send_result: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    screenshot: Mapped[bytes | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CustomerReachCampaign(Base):
    __tablename__ = "customer_reach_campaigns"
    __table_args__ = (
        CheckConstraint("customer_category IN ('ordered', 'inquiry')", name="ck_customer_reach_campaigns_category"),
        CheckConstraint(
            "status IN ('pending', 'locating', 'preparing', 'awaiting_confirmation', 'sending', 'success', 'failed', 'unknown', 'cancelled', 'paused')",
            name="ck_customer_reach_campaigns_status",
        ),
        Index("ix_customer_reach_campaigns_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    customer_category: Mapped[str] = mapped_column(String(16), nullable=False)
    message_text: Mapped[str] = mapped_column(String(10000), nullable=False)
    product_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="simulated")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    step: Mapped[str] = mapped_column(String(64), nullable=False, default="等待执行")
    recipients: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    current_recipient_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    screenshot: Mapped[bytes | None] = mapped_column(nullable=True)
    error_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProductSnapshot(Base):
    __tablename__ = "product_snapshots"
    __table_args__ = (
        CheckConstraint(
            "product_status IN ('unknown', 'active', 'offline')",
            name="ck_product_snapshots_product_status",
        ),
        CheckConstraint(
            "collection_source IN ('html', 'network', 'mixed')",
            name="ck_product_snapshots_collection_source",
        ),
        CheckConstraint(
            "min_order_quantity IS NULL OR min_order_quantity >= 1",
            name="ck_product_snapshots_min_order_quantity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id"), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    shop_name: Mapped[str] = mapped_column(String(255), nullable=False)
    main_image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    image_urls: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    price_min: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    price_max: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    min_order_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_status: Mapped[str] = mapped_column(String(32), nullable=False)
    collection_source: Mapped[str] = mapped_column(String(32), nullable=False)

    skus: Mapped[list["SkuSnapshot"]] = relationship(
        back_populates="product_snapshot",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class SkuSnapshot(Base):
    __tablename__ = "sku_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("product_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    sku_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sku_name: Mapped[str] = mapped_column(String(512), nullable=False)
    stock: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    product_snapshot: Mapped[ProductSnapshot] = relationship(back_populates="skus")


class CollectionRun(Base):
    __tablename__ = "collection_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'success', 'failed')",
            name="ck_collection_runs_status",
        ),
        CheckConstraint(
            "operating_metrics_status IN ('not_attempted', 'success', 'partial', 'no_values', 'failed', 'blocked')",
            name="ck_collection_runs_operating_metrics_status",
        ),
        CheckConstraint(
            "attempt_kind IS NULL OR attempt_kind IN ('first_pass', 'verification_resume', 'operating_metrics_retry')",
            name="ck_collection_runs_attempt_kind",
        ),
        UniqueConstraint("collection_batch_item_id", "attempt_number", name="uq_collection_runs_item_attempt"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id"), nullable=False)
    collection_batch_item_id: Mapped[int | None] = mapped_column(ForeignKey("collection_batch_items.id", name="fk_collection_runs_batch_item"), nullable=True)
    attempt_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempt_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    navigation_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    navigation_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    navigation_terminal_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    operating_metrics_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="not_attempted", server_default="not_attempted"
    )
    error_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(2048), nullable=True)


class CollectionBatch(Base):
    __tablename__ = "collection_batches"
    __table_args__ = (
        CheckConstraint("trigger_kind IN ('manual_selected', 'manual_all_active', 'scheduled', 'manual_single', 'add_links')", name="ck_collection_batches_trigger_kind"),
        CheckConstraint("lifecycle_status IN ('created', 'running', 'terminal')", name="ck_collection_batches_lifecycle"),
        CheckConstraint("outcome_code IS NULL OR outcome_code IN ('success', 'partial_success', 'partial_failure', 'user_ended', 'verification_required', 'collect_failed', 'infrastructure_error', 'interrupted')", name="ck_collection_batches_outcome"),
        CheckConstraint("trigger_kind != 'add_links' OR request_fingerprint IS NOT NULL", name="ck_collection_batches_add_fingerprint"),
        CheckConstraint("planned_products >= 0", name="ck_collection_batches_planned_products"),
        UniqueConstraint("task_id", name="uq_collection_batches_task_id"),
        UniqueConstraint("scheduler_occurrence_key", name="uq_collection_batches_scheduler_occurrence"),
        Index("ix_collection_batches_started_at_id", "started_at", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), nullable=False)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trigger_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lifecycle_status: Mapped[str] = mapped_column(String(16), nullable=False)
    outcome_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    settings_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    planned_products: Mapped[int] = mapped_column(Integer, nullable=False)
    scheduler_occurrence_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    protection_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    protection_details: Mapped[str | None] = mapped_column(String(512), nullable=True)
    circuit_breaker_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    circuit_breaker_cancelled: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    security_error_summary: Mapped[str | None] = mapped_column(String(512), nullable=True)


class CollectionBatchItem(Base):
    __tablename__ = "collection_batch_items"
    __table_args__ = (
        CheckConstraint("execution_status IN ('queued', 'running', 'completed', 'failed', 'not_executed')", name="ck_collection_batch_items_execution_status"),
        CheckConstraint("final_result IS NULL OR final_result IN ('first_pass_success', 'verification_resume_success', 'retry_success', 'final_failed', 'verification_required', 'not_executed', 'business_rejected')", name="ck_collection_batch_items_final_result"),
        CheckConstraint("base_result IS NULL OR base_result IN ('success', 'failed', 'not_attempted')", name="ck_collection_batch_items_base_result"),
        CheckConstraint("attempts_started >= 0 AND page_visits >= 0 AND page_visits_unknown >= 0 AND verification_resume_visits >= 0 AND retry_visits >= 0 AND placeholder_count >= 0 AND source_unavailable_count >= 0 AND loading_count >= 0 AND read_failed_count >= 0", name="ck_collection_batch_items_counts"),
        CheckConstraint("identity_state IN ('pending', 'linked', 'removed')", name="ck_collection_batch_items_identity"),
        CheckConstraint("(identity_state = 'linked' AND competitor_id IS NOT NULL) OR (identity_state IN ('pending', 'removed') AND competitor_id IS NULL)", name="ck_collection_batch_items_identity_fk"),
        CheckConstraint("final_result IS NULL OR final_result != 'business_rejected' OR (execution_status = 'completed' AND base_result IS NOT NULL AND base_result = 'not_attempted')", name="ck_collection_batch_items_business_rejected"),
        UniqueConstraint("batch_id", "position", name="uq_collection_batch_items_position"),
        UniqueConstraint("batch_id", "competitor_id", name="uq_collection_batch_items_competitor"),
        Index("ix_collection_batch_items_batch_status", "batch_id", "execution_status", "final_result"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("collection_batches.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    competitor_id: Mapped[int | None] = mapped_column(ForeignKey("competitors.id"), nullable=True)
    identity_state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    execution_status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", server_default="queued")
    final_result: Mapped[str | None] = mapped_column(String(32), nullable=True)
    base_result: Mapped[str | None] = mapped_column(String(16), nullable=True)
    operating_metrics_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    protection_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    attempts_started: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    page_visits: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    page_visits_unknown: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    verification_resume_visits: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    retry_visits: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    technical_exception_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    placeholder_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    source_unavailable_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    loading_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    read_failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    cancelled_retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    stop_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)


class OperatingMetricObservation(Base):
    __tablename__ = "operating_metric_observations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('observed', 'placeholder', 'loading', 'source_unavailable', 'read_failed')",
            name="ck_operating_metric_observations_status",
        ),
        CheckConstraint(
            "metric_key IN ('listing_time', 'monthly_deal', 'monthly_dropship', 'annual_units', 'annual_orders', 'review_count', 'positive_rate', 'pickup_rate')",
            name="ck_operating_metric_observations_metric_key",
        ),
        CheckConstraint(
            "(status IN ('observed', 'placeholder') AND raw_value IS NOT NULL AND raw_value != '') OR "
            "(status IN ('loading', 'source_unavailable', 'read_failed') AND raw_value IS NULL)",
            name="ck_operating_metric_observations_raw_value",
        ),
        UniqueConstraint("collection_run_id", "metric_key", name="uq_operating_metric_run_key"),
        Index(
            "ix_operating_metric_competitor_key_time_id",
            "competitor_id", "metric_key", "observed_at", "id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id"), nullable=False)
    collection_run_id: Mapped[int] = mapped_column(ForeignKey("collection_runs.id"), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    offer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    metric_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_value: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)


class ChangeEvent(Base):
    __tablename__ = "change_events"
    __table_args__ = (
        CheckConstraint(
            "change_type IN ('price_increase', 'price_decrease', 'stock_increase', 'stock_decrease', 'sku_added', 'sku_removed', 'sku_sold_out', 'sku_restocked', 'min_order_quantity_increase', 'min_order_quantity_decrease', 'product_offline', 'product_online', 'title_changed', 'main_image_changed', 'stock_changed')",
            name="ck_change_events_change_type",
        ),
        CheckConstraint(
            "(change_type = 'product_offline' AND snapshot_id IS NULL) OR "
            "(change_type != 'product_offline' AND snapshot_id IS NOT NULL)",
            name="ck_change_events_snapshot_by_type",
        ),
        Index(
            "ix_change_events_competitor_detected_at_id",
            "competitor_id",
            "detected_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id"), nullable=False)
    snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("product_snapshots.id"), nullable=True)
    collection_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("collection_runs.id", name="fk_change_events_collection_run_id_collection_runs"),
        nullable=True,
    )
    change_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    old_value: Mapped[str | None] = mapped_column(String(512), nullable=True)
    new_value: Mapped[str | None] = mapped_column(String(512), nullable=True)
    delta_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    delta_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


@event.listens_for(CollectionBatchItem, "before_insert")
@event.listens_for(CollectionBatchItem, "before_update")
def _batch_item_identity(_mapper, _connection, item):
    if item.competitor_id is not None:
        item.identity_state = "linked"
    elif item.identity_state in (None, "linked"):
        item.identity_state = "removed"


class CollectionAddInput(Base):
    __tablename__ = "collection_add_inputs"
    __table_args__ = (
        UniqueConstraint("batch_id", "position", name="uq_collection_add_inputs_position"),
        UniqueConstraint("batch_item_id", name="uq_collection_add_inputs_item"),
        CheckConstraint("position >= 0 AND source_line >= 1", name="ck_collection_add_inputs_position"),
        CheckConstraint("input_text IS NULL OR length(input_text) <= 2048", name="ck_collection_add_inputs_length"),
        CheckConstraint("result_code IS NULL OR result_code IN ('added', 'invalid_url', 'duplicate_input', 'already_exists', 'identity_rejected', 'technical_failed', 'verification_required', 'not_executed', 'interrupted')", name="ck_collection_add_inputs_result"),
        CheckConstraint("finished_at IS NULL OR result_code IS NOT NULL", name="ck_collection_add_inputs_finished"),
        CheckConstraint("navigation_confirmed_at IS NULL OR navigation_claimed_at IS NOT NULL", name="ck_collection_add_inputs_navigation"),
        CheckConstraint("identity_removed = 0 OR (input_text IS NULL AND normalized_url IS NULL AND offer_id IS NULL AND related_competitor_id IS NULL AND sanitized_reason IS NULL AND duplicate_of_input_id IS NULL)", name="ck_collection_add_inputs_removed"),
        Index("ix_collection_add_inputs_batch_result", "batch_id", "result_code"),
        Index("ix_collection_add_inputs_offer", "offer_id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("collection_batches.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    source_line: Mapped[int] = mapped_column(Integer, nullable=False)
    input_text: Mapped[str | None] = mapped_column(String(2048))
    normalized_url: Mapped[str | None] = mapped_column(String(2048))
    offer_id: Mapped[str | None] = mapped_column(String(128))
    duplicate_of_input_id: Mapped[int | None] = mapped_column(ForeignKey("collection_add_inputs.id"))
    batch_item_id: Mapped[int | None] = mapped_column(ForeignKey("collection_batch_items.id"))
    related_competitor_id: Mapped[int | None] = mapped_column(ForeignKey("competitors.id"))
    result_code: Mapped[str | None] = mapped_column(String(32))
    error_code: Mapped[str | None] = mapped_column(String(64))
    sanitized_reason: Mapped[str | None] = mapped_column(String(512))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    navigation_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    navigation_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    navigation_terminal_reason: Mapped[str | None] = mapped_column(String(64))
    identity_removed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")

class LibraryProduct(Base):
    __tablename__ = "library_products"
    __table_args__ = (
        CheckConstraint("wholesale_price_cents IS NULL OR (wholesale_price_cents >= 0 AND wholesale_price_cents <= 99999999999)", name="ck_library_products_price"),
        CheckConstraint("version >= 1", name="ck_library_products_version"),
        Index("uq_library_products_model_name", "model", "name", unique=True, sqlite_where=text("model IS NOT NULL")),
        Index("uq_library_products_null_model_name", "name", unique=True, sqlite_where=text("model IS NULL")),
        {"sqlite_autoincrement": True},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    manufacturer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    model: Mapped[str | None] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    parameters: Mapped[str | None] = mapped_column(String(10000))
    selling_points: Mapped[str | None] = mapped_column(String(10000))
    wholesale_price_cents: Mapped[int | None] = mapped_column(Integer)
    price_note: Mapped[str | None] = mapped_column(String(2000))
    category: Mapped[str | None] = mapped_column(String(200))
    structured_attributes: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class LibraryImport(Base):
    __tablename__ = "library_imports"
    __table_args__ = (CheckConstraint("status IN ('ready', 'committed')", name="ck_library_imports_status"),)
    import_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    manufacturer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    preview: Mapped[dict | None] = mapped_column(JSON)
    baseline_digest: Mapped[str | None] = mapped_column(String(64))
    decision_digest: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[dict | None] = mapped_column(JSON)


class LibraryProductVariant(Base):
    __tablename__ = "library_product_variants"
    __table_args__ = (
        UniqueConstraint("id", "product_id"),
        CheckConstraint("version >= 1"),
        Index("uq_library_variant_code", "product_id", "variant_code", unique=True, sqlite_where=text("variant_code IS NOT NULL")),
        Index("uq_library_variant_name", "product_id", "variant_name", text("coalesce(color,'')"), unique=True, sqlite_where=text("variant_code IS NULL")),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("library_products.id", ondelete="CASCADE"), nullable=False)
    variant_code: Mapped[str | None] = mapped_column(String(200))
    variant_name: Mapped[str] = mapped_column(String(200), nullable=False)
    color: Mapped[str | None] = mapped_column(String(200))
    structured_attributes: Mapped[list | None] = mapped_column(JSON)
    notes: Mapped[str | None] = mapped_column(String(10000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class LibraryProductSource(Base):
    __tablename__ = "library_product_sources"
    __table_args__ = (
        UniqueConstraint("id", "product_id"),
        CheckConstraint("version >= 1"),
        CheckConstraint("source_type IN ('quote','catalog','specification','other')"),
        Index("uq_library_source", "product_id", *[text(f"coalesce({field},'')") for field in ("source_company", "source_file_name", "source_page", "source_date", "source_type", "source_excerpt")], unique=True),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("library_products.id", ondelete="CASCADE"), nullable=False)
    source_company: Mapped[str | None] = mapped_column(String(200))
    claimed_manufacturer_name: Mapped[str | None] = mapped_column(String(200))
    source_file_name: Mapped[str | None] = mapped_column(String(500))
    source_page: Mapped[str | None] = mapped_column(String(500))
    source_date: Mapped[str | None] = mapped_column(String(10))
    source_type: Mapped[str] = mapped_column(String(16), nullable=False, default="other")
    source_excerpt: Mapped[str | None] = mapped_column(String(30000))
    notes: Mapped[str | None] = mapped_column(String(10000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class LibraryProductPrice(Base):
    __tablename__ = "library_product_prices"
    __table_args__ = (
        ForeignKeyConstraint(["source_id", "product_id"], ["library_product_sources.id", "library_product_sources.product_id"]),
        ForeignKeyConstraint(["variant_id", "product_id"], ["library_product_variants.id", "library_product_variants.product_id"]),
        CheckConstraint("version >= 1"),
        CheckConstraint("price_type IN ('出厂价','批发价','一件代发价','定制价','平台控价','建议零售价','零售价','其他')"),
        CheckConstraint("tax_mode IN ('unknown','included','excluded')"),
        CheckConstraint("freight_mode IN ('unknown','included','excluded','extra','negotiable')"),
        CheckConstraint("amount_text IS NULL OR (length(amount_text)>0 AND amount_text NOT GLOB '*[^0-9.]*' AND CAST(amount_text AS NUMERIC)>=0)"),
        CheckConstraint("freight_amount_cents IS NULL OR freight_amount_cents >= 0"),
        CheckConstraint("is_default_wholesale IN (0,1) AND (is_default_wholesale=0 OR (price_type='批发价' AND currency_code='CNY' AND price_unit='件' AND amount_text IS NOT NULL AND CAST(amount_text AS NUMERIC)<=999999999.99))"),
        Index("uq_library_default_product", "product_id", unique=True, sqlite_where=text("is_default_wholesale=1 AND variant_id IS NULL")),
        Index("uq_library_default_variant", "product_id", "variant_id", unique=True, sqlite_where=text("is_default_wholesale=1 AND variant_id IS NOT NULL")),
        Index("uq_library_price", "product_id", "source_id", *[text(f"coalesce({field},'')") for field in ("variant_id", "price_type", "price_channel", "currency_code", "price_unit", "quote_date", "min_order_quantity", "min_order_unit", "customization_terms")], unique=True),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("library_products.id", ondelete="CASCADE"), nullable=False)
    variant_id: Mapped[int | None] = mapped_column(Integer)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    price_type: Mapped[str] = mapped_column(String(32), nullable=False)
    price_channel: Mapped[str | None] = mapped_column(String(200))
    amount_text: Mapped[str | None] = mapped_column(String(44))
    currency_code: Mapped[str | None] = mapped_column(String(3))
    price_unit: Mapped[str | None] = mapped_column(String(200))
    min_order_quantity: Mapped[str | None] = mapped_column(String(20))
    min_order_unit: Mapped[str | None] = mapped_column(String(200))
    tax_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    freight_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    freight_amount_cents: Mapped[int | None] = mapped_column(Integer)
    customization_terms: Mapped[str | None] = mapped_column(String(10000))
    terms_text: Mapped[str | None] = mapped_column(String(10000))
    notes: Mapped[str | None] = mapped_column(String(10000))
    source_excerpt: Mapped[str | None] = mapped_column(String(10000))
    quote_date: Mapped[str | None] = mapped_column(String(10))
    is_default_wholesale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
