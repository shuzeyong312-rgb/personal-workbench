from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ChangeEvent, Competitor


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


class DashboardResponse(BaseModel):
    date: date
    stats: DashboardStatsResponse
    items: list[DashboardItemResponse]


def business_day_bounds(now: datetime | None = None) -> tuple[date, datetime, datetime]:
    current = (now or datetime.now(timezone.utc)).astimezone(BUSINESS_TIMEZONE)
    local_start = datetime.combine(current.date(), time.min, tzinfo=BUSINESS_TIMEZONE)
    local_end = local_start + timedelta(days=1)
    return (
        current.date(),
        local_start.astimezone(timezone.utc).replace(tzinfo=None),
        local_end.astimezone(timezone.utc).replace(tzinfo=None),
    )


@router.get("/today", response_model=DashboardResponse)
def get_today_dashboard(db: Session = Depends(get_db)) -> DashboardResponse:
    business_date, start_utc, end_utc = business_day_bounds()
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

    return DashboardResponse(
        date=business_date,
        stats=DashboardStatsResponse(
            monitored_competitors=monitored_competitors,
            changed_competitors=len(items),
            change_events=len(rows),
        ),
        items=list(items.values()),
    )
