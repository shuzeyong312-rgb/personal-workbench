from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
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
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int | None] = mapped_column(
        ForeignKey("competitor_groups.id", name="fk_competitors_group_id_competitor_groups"), nullable=True
    )
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
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id"), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    shop_name: Mapped[str] = mapped_column(String(255), nullable=False)
    main_image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    price_min: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    price_max: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
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
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(2048), nullable=True)


class ChangeEvent(Base):
    __tablename__ = "change_events"
    __table_args__ = (
        CheckConstraint(
            "change_type IN ('price_increase', 'price_decrease', 'sku_added', 'sku_removed', 'stock_changed', 'title_changed')",
            name="ck_change_events_change_type",
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
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("product_snapshots.id"), nullable=False)
    change_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    old_value: Mapped[str | None] = mapped_column(String(512), nullable=True)
    new_value: Mapped[str | None] = mapped_column(String(512), nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
