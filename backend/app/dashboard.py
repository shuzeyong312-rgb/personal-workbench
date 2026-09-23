from datetime import date, datetime, time, timedelta, timezone
from html import unescape
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ChangeEvent, CollectionRun, Competitor, ProductSnapshot, SkuSnapshot


router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
try:
    BUSINESS_TIMEZONE = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:
    BUSINESS_TIMEZONE = timezone(timedelta(hours=8))


class DashboardPrimaryChangeResponse(BaseModel):
    id: int
    change_type: str
    collection_run_id: int | None
    entity_key: str | None
    sku_name: str | None
    old_value: str | None
    new_value: str | None
    delta_value: str | None
    delta_rate: str | None
    detected_at: datetime


class DashboardStockTotalChangeResponse(BaseModel):
    old_total: int | None
    new_total: int | None


class DashboardItemResponse(BaseModel):
    competitor_id: int
    title: str | None
    shop_name: str | None
    main_image_url: str | None
    group_id: int | None
    last_collected_at: datetime | None
    change_count: int
    change_types: list[str]
    latest_change_at: datetime
    primary_change: DashboardPrimaryChangeResponse | None
    stock_changed_sku_count: int | None
    stock_total_change: DashboardStockTotalChangeResponse | None
    sku_added_count: int
    sku_removed_count: int


class DashboardStatsResponse(BaseModel):
    monitored_competitors: int
    changed_competitors: int
    change_events: int
    price_changed_competitors: int
    stock_changed_competitors: int
    sku_changed_competitors: int
    failed_collections: int


class CollectionSummaryResponse(BaseModel):
    last_collection_at: datetime | None
    success_runs: int
    failed_runs: int
    average_duration_seconds: float | None


class DashboardTrendPointResponse(BaseModel):
    date: date
    price_changes: int
    stock_changes: int
    sku_changes: int
    failed_collections: int


class DashboardResponse(BaseModel):
    date: date
    stats: DashboardStatsResponse
    items: list[DashboardItemResponse]
    collection_summary: CollectionSummaryResponse
    trend_7d: list[DashboardTrendPointResponse]


def business_day_bounds(now: datetime | None = None) -> tuple[date, datetime, datetime]:
    current = (now or datetime.now(timezone.utc)).astimezone(BUSINESS_TIMEZONE)
    start_utc, end_utc = business_date_utc_bounds(current.date())
    return (
        current.date(),
        start_utc,
        end_utc,
    )


def business_date_utc_bounds(business_date: date) -> tuple[datetime, datetime]:
    local_start = datetime.combine(business_date, time.min, tzinfo=BUSINESS_TIMEZONE)
    local_end = local_start + timedelta(days=1)
    return (
        local_start.astimezone(timezone.utc).replace(tzinfo=None),
        local_end.astimezone(timezone.utc).replace(tzinfo=None),
    )


def business_date_for_utc(value: datetime) -> date:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(BUSINESS_TIMEZONE).date()


def _average_duration_seconds(runs: list[CollectionRun]) -> float | None:
    durations = [
        (run.finished_at - run.started_at).total_seconds()
        for run in runs
        if run.finished_at is not None
    ]
    return round(sum(durations) / len(durations), 2) if durations else None


_PRICE_CHANGE_TYPES = frozenset({"price_increase", "price_decrease"})
_STOCK_CHANGE_TYPES = frozenset(
    {"stock_increase", "stock_decrease", "sku_sold_out", "sku_restocked", "stock_changed"}
)
_SKU_CHANGE_TYPES = frozenset({"sku_added", "sku_removed"})
_CHANGE_PRIORITY = {
    "price_increase": 0,
    "price_decrease": 0,
    "stock_increase": 1,
    "stock_decrease": 1,
    "sku_sold_out": 1,
    "sku_restocked": 1,
    "stock_changed": 1,
    "sku_added": 2,
    "sku_removed": 2,
    "min_order_quantity_increase": 3,
    "min_order_quantity_decrease": 3,
    "main_image_changed": 4,
    "title_changed": 5,
}
_LIFECYCLE_CHANGE_TYPES = frozenset({"product_offline", "product_online"})


def _sku_names(
    db: Session,
    events: list[ChangeEvent],
) -> tuple[dict[tuple[int, str], str], dict[tuple[int, str], str]]:
    stock_events = [event for event in events if event.entity_key is not None]
    if not stock_events:
        return {}, {}
    competitor_ids = {event.competitor_id for event in stock_events}
    sku_ids = {event.entity_key for event in stock_events if event.entity_key is not None}
    rows = db.execute(
        select(
            ProductSnapshot.competitor_id,
            ProductSnapshot.id,
            SkuSnapshot.sku_id,
            SkuSnapshot.sku_name,
            ProductSnapshot.captured_at,
            SkuSnapshot.id,
        )
        .join(SkuSnapshot, SkuSnapshot.product_snapshot_id == ProductSnapshot.id)
        .where(
            ProductSnapshot.competitor_id.in_(competitor_ids),
            SkuSnapshot.sku_id.in_(sku_ids),
        )
        .order_by(ProductSnapshot.captured_at.desc(), ProductSnapshot.id.desc(), SkuSnapshot.id.desc())
    ).all()
    historical: dict[tuple[int, str], str] = {}
    exact: dict[tuple[int, str], str] = {}
    for competitor_id, snapshot_id, sku_id, sku_name, _captured_at, _sku_snapshot_id in rows:
        display_name = unescape(sku_name).strip() if sku_name else ""
        if not display_name:
            continue
        historical.setdefault((competitor_id, sku_id), display_name)
        exact.setdefault((snapshot_id, sku_id), display_name)
    return exact, historical


def _calculate_total_stock(skus: list[SkuSnapshot]) -> int | None:
    if not skus or any(sku.stock is None for sku in skus):
        return None
    return sum(sku.stock for sku in skus if sku.stock is not None)


def _stock_total_changes(
    db: Session,
    primary_stock_events: list[ChangeEvent],
) -> dict[int, DashboardStockTotalChangeResponse]:
    current_snapshot_ids = {event.snapshot_id for event in primary_stock_events}
    if not current_snapshot_ids:
        return {}

    current_snapshots = list(
        db.scalars(
            select(ProductSnapshot).where(ProductSnapshot.id.in_(current_snapshot_ids))
        ).all()
    )
    if not current_snapshots:
        return {}

    competitor_ids = {snapshot.competitor_id for snapshot in current_snapshots}
    snapshots = list(
        db.scalars(
            select(ProductSnapshot)
            .where(ProductSnapshot.competitor_id.in_(competitor_ids))
            .order_by(
                ProductSnapshot.competitor_id.asc(),
                ProductSnapshot.captured_at.asc(),
                ProductSnapshot.id.asc(),
            )
        ).all()
    )
    previous_by_snapshot_id: dict[int, ProductSnapshot | None] = {}
    last_by_competitor: dict[int, ProductSnapshot] = {}
    for snapshot in snapshots:
        previous_by_snapshot_id[snapshot.id] = last_by_competitor.get(snapshot.competitor_id)
        last_by_competitor[snapshot.competitor_id] = snapshot

    previous_snapshot_ids = {
        previous.id
        for snapshot_id, previous in previous_by_snapshot_id.items()
        if snapshot_id in current_snapshot_ids and previous is not None
    }
    sku_snapshot_ids = current_snapshot_ids | previous_snapshot_ids
    sku_by_snapshot: dict[int, list[SkuSnapshot]] = {}
    for sku in db.scalars(
        select(SkuSnapshot)
        .where(SkuSnapshot.product_snapshot_id.in_(sku_snapshot_ids))
        .order_by(SkuSnapshot.product_snapshot_id.asc(), SkuSnapshot.id.asc())
    ).all():
        sku_by_snapshot.setdefault(sku.product_snapshot_id, []).append(sku)

    current_by_id = {snapshot.id: snapshot for snapshot in current_snapshots}
    return {
        snapshot_id: DashboardStockTotalChangeResponse(
            old_total=_calculate_total_stock(
                sku_by_snapshot.get(previous.id, []) if previous is not None else []
            ),
            new_total=_calculate_total_stock(sku_by_snapshot.get(snapshot_id, [])),
        )
        for snapshot_id, snapshot in current_by_id.items()
        for previous in [previous_by_snapshot_id.get(snapshot_id)]
    }


def _primary_event(events: list[ChangeEvent]) -> ChangeEvent:
    lifecycle_events = [event for event in events if event.change_type in _LIFECYCLE_CHANGE_TYPES]
    if lifecycle_events:
        return max(lifecycle_events, key=lambda event: (event.detected_at, event.id))
    candidates = [event for event in events if event.change_type in _CHANGE_PRIORITY]
    if not candidates:
        return max(events, key=lambda event: (event.detected_at, event.id))
    priority = min(_CHANGE_PRIORITY[event.change_type] for event in candidates)
    candidates = [event for event in candidates if _CHANGE_PRIORITY[event.change_type] == priority]
    if any(event.change_type in _PRICE_CHANGE_TYPES and event.entity_key is None for event in candidates):
        candidates = [
            event
            for event in candidates
            if event.change_type not in _PRICE_CHANGE_TYPES or event.entity_key is None
        ]
    return max(candidates, key=lambda event: (event.detected_at, event.id))


def _change_type_display_key(change_type: str) -> tuple[int, int]:
    if change_type == "product_offline":
        return (0, 0)
    if change_type == "product_online":
        return (0, 1)
    return (1, _CHANGE_PRIORITY.get(change_type, 99))


@router.get("/today", response_model=DashboardResponse)
def get_today_dashboard(db: Session = Depends(get_db)) -> DashboardResponse:
    business_date, start_utc, end_utc = business_day_bounds()
    trend_start_utc, _ = business_date_utc_bounds(business_date - timedelta(days=6))
    monitored_competitors = int(
        db.scalar(select(func.count()).select_from(Competitor).where(Competitor.is_active.is_(True))) or 0
    )
    rows = db.execute(
        select(Competitor, ChangeEvent)
        .join(ChangeEvent, ChangeEvent.competitor_id == Competitor.id)
        .where(
            Competitor.is_active.is_(True),
            ChangeEvent.detected_at >= start_utc,
            ChangeEvent.detected_at < end_utc,
        )
        .order_by(ChangeEvent.detected_at.desc(), ChangeEvent.id.desc())
    ).all()

    aggregates: dict[int, dict[str, object]] = {}
    price_changed_competitors: set[int] = set()
    stock_changed_competitors: set[int] = set()
    sku_changed_competitors: set[int] = set()
    for competitor, event in rows:
        aggregate = aggregates.setdefault(
            competitor.id,
            {
                "competitor": competitor,
                "events": [],
                "stock_sku_ids": set(),
                "stock_key_unknown": False,
                "sku_added_count": 0,
                "sku_removed_count": 0,
            },
        )
        aggregate["events"].append(event)  # type: ignore[union-attr]
        if event.change_type in _STOCK_CHANGE_TYPES:
            if event.entity_key is None:
                aggregate["stock_key_unknown"] = True
            else:
                aggregate["stock_sku_ids"].add(event.entity_key)  # type: ignore[union-attr]
        elif event.change_type == "sku_added":
            aggregate["sku_added_count"] += 1  # type: ignore[operator]
        elif event.change_type == "sku_removed":
            aggregate["sku_removed_count"] += 1  # type: ignore[operator]
        if event.change_type in _PRICE_CHANGE_TYPES:
            price_changed_competitors.add(competitor.id)
        elif event.change_type in _STOCK_CHANGE_TYPES:
            stock_changed_competitors.add(competitor.id)
        elif event.change_type in _SKU_CHANGE_TYPES:
            sku_changed_competitors.add(competitor.id)

    event_list = [event for aggregate in aggregates.values() for event in aggregate["events"]]  # type: ignore[union-attr]
    exact_sku_names, historical_sku_names = _sku_names(db, event_list)
    primary_stock_events = [
        primary
        for aggregate in aggregates.values()
        for primary in [_primary_event(aggregate["events"])]  # type: ignore[union-attr]
        if primary.change_type in _STOCK_CHANGE_TYPES
    ]
    stock_total_changes = _stock_total_changes(db, primary_stock_events)
    items = []
    for aggregate in aggregates.values():
        competitor = aggregate["competitor"]
        events = aggregate["events"]
        primary = _primary_event(events)
        event_types = []
        for event in events:
            if event.change_type not in event_types:
                event_types.append(event.change_type)
        event_types.sort(key=_change_type_display_key)
        primary_sku_name = None
        if primary.entity_key is not None:
            primary_sku_name = exact_sku_names.get(
                (primary.snapshot_id, primary.entity_key),
                historical_sku_names.get((competitor.id, primary.entity_key)),
            )
        stock_sku_count = None if aggregate["stock_key_unknown"] else len(aggregate["stock_sku_ids"])
        items.append(
            DashboardItemResponse(
                competitor_id=competitor.id,
                title=competitor.title,
                shop_name=competitor.shop_name,
                main_image_url=competitor.main_image_url,
                group_id=competitor.group_id,
                last_collected_at=competitor.last_collected_at,
                change_count=len(events),
                change_types=event_types,
                latest_change_at=events[0].detected_at,
                primary_change=DashboardPrimaryChangeResponse(
                    id=primary.id,
                    change_type=primary.change_type,
                    collection_run_id=primary.collection_run_id,
                    entity_key=primary.entity_key,
                    sku_name=primary_sku_name,
                    old_value=primary.old_value,
                    new_value=primary.new_value,
                    delta_value=str(primary.delta_value) if primary.delta_value is not None else None,
                    delta_rate=str(primary.delta_rate) if primary.delta_rate is not None else None,
                    detected_at=primary.detected_at,
                ),
                stock_changed_sku_count=stock_sku_count,
                stock_total_change=stock_total_changes.get(primary.snapshot_id)
                if primary.change_type in _STOCK_CHANGE_TYPES
                else None,
                sku_added_count=aggregate["sku_added_count"],
                sku_removed_count=aggregate["sku_removed_count"],
            ),
        )
    items.sort(key=lambda item: (item.latest_change_at, item.competitor_id), reverse=True)

    today_runs = list(
        db.scalars(
            select(CollectionRun).where(
                CollectionRun.started_at >= start_utc,
                CollectionRun.started_at < end_utc,
            )
        ).all()
    )
    last_finished_at = db.scalar(
        select(func.max(CollectionRun.finished_at)).where(CollectionRun.finished_at.is_not(None))
    )
    last_collection_at = last_finished_at or db.scalar(select(func.max(CollectionRun.started_at)))

    trend_events = db.execute(
        select(ChangeEvent.detected_at, ChangeEvent.change_type)
        .join(Competitor, Competitor.id == ChangeEvent.competitor_id)
        .where(
            Competitor.is_active.is_(True),
            ChangeEvent.detected_at >= trend_start_utc,
            ChangeEvent.detected_at < end_utc,
        )
    ).all()
    trend_runs = db.scalars(
        select(CollectionRun).where(
            CollectionRun.started_at >= trend_start_utc,
            CollectionRun.started_at < end_utc,
            CollectionRun.status == "failed",
        )
    ).all()
    trend_counts = {
        day: {"price_changes": 0, "stock_changes": 0, "sku_changes": 0, "failed_collections": 0}
        for day in (business_date - timedelta(days=offset) for offset in range(6, -1, -1))
    }
    for detected_at, change_type in trend_events:
        day = business_date_for_utc(detected_at)
        if day not in trend_counts:
            continue
        if change_type in {"price_increase", "price_decrease"}:
            trend_counts[day]["price_changes"] += 1
        elif change_type in _STOCK_CHANGE_TYPES:
            trend_counts[day]["stock_changes"] += 1
        elif change_type in {"sku_added", "sku_removed"}:
            trend_counts[day]["sku_changes"] += 1
    for run in trend_runs:
        day = business_date_for_utc(run.started_at)
        if day in trend_counts:
            trend_counts[day]["failed_collections"] += 1

    return DashboardResponse(
        date=business_date,
        stats=DashboardStatsResponse(
            monitored_competitors=monitored_competitors,
            changed_competitors=len(items),
            change_events=len(rows),
            price_changed_competitors=len(price_changed_competitors),
            stock_changed_competitors=len(stock_changed_competitors),
            sku_changed_competitors=len(sku_changed_competitors),
            failed_collections=sum(run.status == "failed" for run in today_runs),
        ),
        items=items,
        collection_summary=CollectionSummaryResponse(
            last_collection_at=last_collection_at,
            success_runs=sum(run.status == "success" for run in today_runs),
            failed_runs=sum(run.status == "failed" for run in today_runs),
            average_duration_seconds=_average_duration_seconds(today_runs),
        ),
        trend_7d=[
            DashboardTrendPointResponse(date=day, **counts)
            for day, counts in trend_counts.items()
        ],
    )
