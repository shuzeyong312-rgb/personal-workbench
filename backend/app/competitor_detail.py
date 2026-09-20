from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.competitors import _price_text, error
from app.database import get_db
from app.models import ChangeEvent, CollectionRun, Competitor, ProductSnapshot, SkuSnapshot


router = APIRouter(prefix="/api/competitors", tags=["competitor-detail"])


class DetailCompetitorResponse(BaseModel):
    id: int
    platform: str
    offer_id: str
    url: str
    group_id: int | None
    title: str | None
    shop_name: str | None
    main_image_url: str | None
    status: str
    is_active: bool
    created_at: datetime
    last_collected_at: datetime | None


class LatestSnapshotDetailResponse(BaseModel):
    id: int
    captured_at: datetime
    price_min: str | None
    price_max: str | None
    product_status: str
    sku_count: int


class LatestSkuResponse(BaseModel):
    sku_id: str
    sku_name: str
    stock: int | None
    price: str | None


class PriceTrendResponse(BaseModel):
    snapshot_id: int
    captured_at: datetime
    price_min: str | None
    price_max: str | None


class DetailChangeResponse(BaseModel):
    id: int
    snapshot_id: int
    change_type: str
    entity_key: str | None
    old_value: str | None
    new_value: str | None
    detected_at: datetime


class DetailCollectionRunResponse(BaseModel):
    id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    error_type: str | None
    error_message: str | None


class CompetitorDetailResponse(BaseModel):
    range_days: int
    competitor: DetailCompetitorResponse
    latest_snapshot: LatestSnapshotDetailResponse | None
    latest_skus: list[LatestSkuResponse]
    price_trend: list[PriceTrendResponse]
    recent_changes: list[DetailChangeResponse]
    recent_collection_runs: list[DetailCollectionRunResponse]


@router.get("/{competitor_id}/detail", response_model=CompetitorDetailResponse)
def get_competitor_detail(
    competitor_id: int,
    days: int = Query(default=7),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    if days not in (7, 30):
        raise HTTPException(status_code=422, detail="days must be 7 or 30")
    competitor = db.get(Competitor, competitor_id)
    if competitor is None:
        raise error("competitor_not_found", "竞品不存在", 404)

    latest_snapshot = db.scalar(
        select(ProductSnapshot)
        .where(ProductSnapshot.competitor_id == competitor_id)
        .order_by(ProductSnapshot.captured_at.desc(), ProductSnapshot.id.desc())
        .limit(1)
    )
    latest_skus = (
        list(
            db.scalars(
                select(SkuSnapshot)
                .where(SkuSnapshot.product_snapshot_id == latest_snapshot.id)
                .order_by(SkuSnapshot.id.asc())
            ).all()
        )
        if latest_snapshot is not None
        else []
    )

    now = datetime.now(timezone.utc)
    trend = list(
        db.scalars(
            select(ProductSnapshot)
            .where(
                ProductSnapshot.competitor_id == competitor_id,
                ProductSnapshot.captured_at >= now - timedelta(days=days),
                ProductSnapshot.captured_at <= now,
            )
            .order_by(ProductSnapshot.captured_at.asc(), ProductSnapshot.id.asc())
        ).all()
    )
    changes = list(
        db.scalars(
            select(ChangeEvent)
            .where(ChangeEvent.competitor_id == competitor_id)
            .order_by(ChangeEvent.detected_at.desc(), ChangeEvent.id.desc())
            .limit(20)
        ).all()
    )
    collection_runs = list(
        db.scalars(
            select(CollectionRun)
            .where(CollectionRun.competitor_id == competitor_id)
            .order_by(CollectionRun.started_at.desc(), CollectionRun.id.desc())
            .limit(20)
        ).all()
    )

    return {
        "range_days": days,
        "competitor": competitor,
        "latest_snapshot": (
            {
                "id": latest_snapshot.id,
                "captured_at": latest_snapshot.captured_at,
                "price_min": _price_text(latest_snapshot.price_min),
                "price_max": _price_text(latest_snapshot.price_max),
                "product_status": latest_snapshot.product_status,
                "sku_count": len(latest_skus),
            }
            if latest_snapshot is not None
            else None
        ),
        "latest_skus": [
            {
                "sku_id": sku.sku_id,
                "sku_name": sku.sku_name,
                "stock": sku.stock,
                "price": _price_text(sku.price),
            }
            for sku in latest_skus
        ],
        "price_trend": [
            {
                "snapshot_id": snapshot.id,
                "captured_at": snapshot.captured_at,
                "price_min": _price_text(snapshot.price_min),
                "price_max": _price_text(snapshot.price_max),
            }
            for snapshot in trend
        ],
        "recent_changes": changes,
        "recent_collection_runs": collection_runs,
    }
