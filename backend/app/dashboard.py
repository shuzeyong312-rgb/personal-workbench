from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ChangeEvent, CollectionRun, Competitor


router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
try:
    BUSINESS_TIMEZONE = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:
    BUSINESS_TIMEZONE = timezone(timedelta(hours=8))


class DashboardChangeResponse(BaseModel):
    id: int
    change_type: str
    entity_key: str | None
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
    changes: list[DashboardChangeResponse]


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

    items: dict[int, DashboardItemResponse] = {}
    price_changed_competitors: set[int] = set()
    stock_changed_competitors: set[int] = set()
    sku_changed_competitors: set[int] = set()
    for competitor, event in rows:
        item = items.setdefault(
            competitor.id,
            DashboardItemResponse(
                competitor_id=competitor.id,
                title=competitor.title,
                shop_name=competitor.shop_name,
                main_image_url=competitor.main_image_url,
                group_id=competitor.group_id,
                last_collected_at=competitor.last_collected_at,
                changes=[],
            ),
        )
        item.changes.append(
            DashboardChangeResponse(
                id=event.id,
                change_type=event.change_type,
                entity_key=event.entity_key,
                old_value=event.old_value,
                new_value=event.new_value,
                detected_at=event.detected_at,
            )
        )
        if event.change_type in {"price_increase", "price_decrease"}:
            price_changed_competitors.add(competitor.id)
        elif event.change_type == "stock_changed":
            stock_changed_competitors.add(competitor.id)
        elif event.change_type in {"sku_added", "sku_removed"}:
            sku_changed_competitors.add(competitor.id)

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
        items=list(items.values()),
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
