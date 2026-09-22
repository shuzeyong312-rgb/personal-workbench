from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from html import unescape

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.competitors import _price_text, error
from app.dashboard import business_date_for_utc, business_date_utc_bounds, business_day_bounds
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
    image_urls: list[str] | None
    min_order_quantity: int | None
    product_status: str
    sku_count: int
    total_stock: int | None


class LatestSkuResponse(BaseModel):
    sku_id: str
    sku_name: str | None
    stock: int | None
    price: str | None


class DailyTrendResponse(BaseModel):
    date: date
    snapshot_id: int | None
    captured_at: datetime | None
    price_min: str | None
    price_max: str | None
    total_stock: int | None


class DetailChangeResponse(BaseModel):
    id: int
    snapshot_id: int
    change_type: str
    entity_key: str | None
    old_value: str | None
    new_value: str | None
    detected_at: datetime
    sku_name: str | None = None


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
    latest_price_change: DetailChangeResponse | None
    daily_trend: list[DailyTrendResponse]
    recent_changes: list[DetailChangeResponse]
    recent_collection_runs: list[DetailCollectionRunResponse]


def calculate_total_stock(skus: Sequence[SkuSnapshot]) -> int | None:
    """Return a complete SKU total, preserving unknown stock as unknown."""
    if not skus or any(sku.stock is None for sku in skus):
        return None
    return sum(sku.stock for sku in skus if sku.stock is not None)


def _display_sku_name(value: str | None) -> str | None:
    if value is None:
        return None
    name = unescape(value).strip()
    return name or None


def _change_sku_names(
    db: Session,
    competitor_id: int,
    changes: Sequence[ChangeEvent],
) -> dict[tuple[int, str], str | None]:
    stock_changes = [
        change
        for change in changes
        if change.change_type == "stock_changed" and change.entity_key
    ]
    if not stock_changes:
        return {}

    snapshot_ids = {change.snapshot_id for change in stock_changes}
    sku_ids = {change.entity_key for change in stock_changes if change.entity_key is not None}
    exact_names: dict[tuple[int, str], str] = {}
    exact_rows = db.execute(
        select(SkuSnapshot.product_snapshot_id, SkuSnapshot.sku_id, SkuSnapshot.sku_name).where(
            SkuSnapshot.product_snapshot_id.in_(snapshot_ids),
            SkuSnapshot.sku_id.in_(sku_ids),
        )
    ).all()
    for snapshot_id, sku_id, sku_name in exact_rows:
        display_name = _display_sku_name(sku_name)
        if display_name is not None:
            exact_names[(snapshot_id, sku_id)] = display_name

    historical_names: dict[str, str] = {}
    historical_rows = db.execute(
        select(SkuSnapshot.sku_id, SkuSnapshot.sku_name)
        .join(ProductSnapshot, ProductSnapshot.id == SkuSnapshot.product_snapshot_id)
        .where(
            ProductSnapshot.competitor_id == competitor_id,
            SkuSnapshot.sku_id.in_(sku_ids),
        )
        .order_by(
            SkuSnapshot.sku_id.asc(),
            ProductSnapshot.captured_at.desc(),
            ProductSnapshot.id.desc(),
            SkuSnapshot.id.desc(),
        )
    ).all()
    for sku_id, sku_name in historical_rows:
        if sku_id in historical_names:
            continue
        display_name = _display_sku_name(sku_name)
        if display_name is not None:
            historical_names[sku_id] = display_name

    return {
        (change.snapshot_id, change.entity_key): exact_names.get(
            (change.snapshot_id, change.entity_key),
            historical_names.get(change.entity_key),
        )
        for change in stock_changes
        if change.entity_key is not None
    }


def _change_response(
    change: ChangeEvent,
    sku_names: dict[tuple[int, str], str | None],
) -> dict[str, object]:
    sku_name = None
    if change.change_type == "stock_changed" and change.entity_key:
        sku_name = sku_names.get((change.snapshot_id, change.entity_key))
    return {
        "id": change.id,
        "snapshot_id": change.snapshot_id,
        "change_type": change.change_type,
        "entity_key": change.entity_key,
        "old_value": change.old_value,
        "new_value": change.new_value,
        "detected_at": change.detected_at,
        "sku_name": sku_name,
    }


def _daily_snapshot_selection(
    db: Session,
    competitor_id: int,
    days: int,
) -> tuple[list[date], dict[date, ProductSnapshot]]:
    current_date, _, end_utc = business_day_bounds()
    first_date = current_date - timedelta(days=days - 1)
    start_utc, _ = business_date_utc_bounds(first_date)
    snapshots = list(
        db.scalars(
            select(ProductSnapshot)
            .where(
                ProductSnapshot.competitor_id == competitor_id,
                ProductSnapshot.captured_at >= start_utc,
                ProductSnapshot.captured_at < end_utc,
            )
            .order_by(ProductSnapshot.captured_at.desc(), ProductSnapshot.id.desc())
        ).all()
    )
    latest_by_date: dict[date, ProductSnapshot] = {}
    for snapshot in snapshots:
        snapshot_date = business_date_for_utc(snapshot.captured_at)
        if first_date <= snapshot_date <= current_date and snapshot_date not in latest_by_date:
            latest_by_date[snapshot_date] = snapshot
    dates = [first_date + timedelta(days=offset) for offset in range(days)]
    return dates, latest_by_date


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
    dates, daily_snapshots = _daily_snapshot_selection(db, competitor_id, days)
    selected_snapshot_ids = {snapshot.id for snapshot in daily_snapshots.values()}
    if latest_snapshot is not None:
        selected_snapshot_ids.add(latest_snapshot.id)

    skus_by_snapshot: defaultdict[int, list[SkuSnapshot]] = defaultdict(list)
    if selected_snapshot_ids:
        selected_skus = db.scalars(
            select(SkuSnapshot)
            .where(SkuSnapshot.product_snapshot_id.in_(selected_snapshot_ids))
            .order_by(SkuSnapshot.product_snapshot_id.asc(), SkuSnapshot.id.asc())
        ).all()
        for sku in selected_skus:
            skus_by_snapshot[sku.product_snapshot_id].append(sku)

    latest_skus = skus_by_snapshot.get(latest_snapshot.id, []) if latest_snapshot is not None else []
    latest_price_change = db.scalar(
        select(ChangeEvent)
        .where(
            ChangeEvent.competitor_id == competitor_id,
            ChangeEvent.change_type.in_(("price_increase", "price_decrease")),
        )
        .order_by(ChangeEvent.detected_at.desc(), ChangeEvent.id.desc())
        .limit(1)
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
    change_sku_names = _change_sku_names(db, competitor_id, changes)

    daily_trend = []
    for snapshot_date in dates:
        snapshot = daily_snapshots.get(snapshot_date)
        snapshot_skus = skus_by_snapshot.get(snapshot.id, []) if snapshot is not None else []
        daily_trend.append(
            {
                "date": snapshot_date,
                "snapshot_id": snapshot.id if snapshot is not None else None,
                "captured_at": snapshot.captured_at if snapshot is not None else None,
                "price_min": _price_text(snapshot.price_min) if snapshot is not None else None,
                "price_max": _price_text(snapshot.price_max) if snapshot is not None else None,
                "total_stock": calculate_total_stock(snapshot_skus) if snapshot is not None else None,
            }
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
                "image_urls": latest_snapshot.image_urls,
                "min_order_quantity": latest_snapshot.min_order_quantity,
                "product_status": latest_snapshot.product_status,
                "sku_count": len(latest_skus),
                "total_stock": calculate_total_stock(latest_skus),
            }
            if latest_snapshot is not None
            else None
        ),
        "latest_skus": [
            {
                "sku_id": sku.sku_id,
                "sku_name": _display_sku_name(sku.sku_name),
                "stock": sku.stock,
                "price": _price_text(sku.price),
            }
            for sku in latest_skus
        ],
        "latest_price_change": (
            _change_response(latest_price_change, change_sku_names)
            if latest_price_change is not None
            else None
        ),
        "daily_trend": daily_trend,
        "recent_changes": [_change_response(change, change_sku_names) for change in changes],
        "recent_collection_runs": collection_runs,
    }
