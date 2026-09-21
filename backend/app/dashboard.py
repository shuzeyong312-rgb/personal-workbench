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
    entity_key: str | None
    sku_name: str | None
    old_value: str | None
    new_value: str | None
    detected_at: datetime


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


_CHANGE_PRIORITY = {
    "price_increase": 0,
    "price_decrease": 0,
    "stock_changed": 1,
    "sku_added": 2,
    "sku_removed": 2,
    "title_changed": 3,
}


def _sku_names(
    db: Session,
    events: list[ChangeEvent],
) -> tuple[dict[tuple[int, str], str], dict[tuple[int, str], str]]:
    stock_events = [
        event for event in events if event.change_type == "stock_changed" and event.entity_key is not None
    ]
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


def _primary_event(events: list[ChangeEvent]) -> ChangeEvent:
    return min(
        enumerate(events),
        key=lambda pair: (_CHANGE_PRIORITY[pair[1].change_type], pair[0]),
    )[1]


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
        if event.change_type == "stock_changed":
            if event.entity_key is None:
                aggregate["stock_key_unknown"] = True
            else:
                aggregate["stock_sku_ids"].add(event.entity_key)  # type: ignore[union-attr]
        elif event.change_type == "sku_added":
            aggregate["sku_added_count"] += 1  # type: ignore[operator]
        elif event.change_type == "sku_removed":
            aggregate["sku_removed_count"] += 1  # type: ignore[operator]
        if event.change_type in {"price_increase", "price_decrease"}:
            price_changed_competitors.add(competitor.id)
        elif event.change_type == "stock_changed":
            stock_changed_competitors.add(competitor.id)
        elif event.change_type in {"sku_added", "sku_removed"}:
            sku_changed_competitors.add(competitor.id)

    event_list = [event for aggregate in aggregates.values() for event in aggregate["events"]]  # type: ignore[union-attr]
    exact_sku_names, historical_sku_names = _sku_names(db, event_list)
    items = []
    for aggregate in aggregates.values():
        competitor = aggregate["competitor"]
        events = aggregate["events"]
        primary = _primary_event(events)
        event_types = []
        for event in events:
            if event.change_type not in event_types:
                event_types.append(event.change_type)
        event_types.sort(key=lambda change_type: _CHANGE_PRIORITY[change_type])
        primary_sku_name = None
        if primary.change_type == "stock_changed" and primary.entity_key is not None:
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
                    entity_key=primary.entity_key,
                    sku_name=primary_sku_name,
                    old_value=primary.old_value,
                    new_value=primary.new_value,
                    detected_at=primary.detected_at,
                ),
                stock_changed_sku_count=stock_sku_count,
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
        elif change_type == "stock_changed":
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
