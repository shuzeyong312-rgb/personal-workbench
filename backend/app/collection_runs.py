from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import CollectionRun, Competitor


PAGE_SIZE = 20

router = APIRouter(prefix="/api/collection-runs", tags=["collection-runs"])


class CollectionRunItemResponse(BaseModel):
    id: int
    competitor_id: int
    ownership: Literal["self", "competitor"]
    title: str | None
    offer_id: str
    shop_name: str | None
    started_at: datetime
    finished_at: datetime | None
    status: str
    error_type: str | None
    error_message: str | None
    duration_seconds: float | None


class CollectionRunListResponse(BaseModel):
    items: list[CollectionRunItemResponse]
    total: int
    page: int
    page_size: int


def _duration_seconds(run: CollectionRun) -> float | None:
    if run.finished_at is None:
        return None
    return max(0.0, (run.finished_at - run.started_at).total_seconds())


@router.get("", response_model=CollectionRunListResponse)
def list_collection_runs(
    search: str | None = None,
    status: Literal["all", "success", "failed"] = "all",
    ownership: Literal["all", "self", "competitor"] = "all",
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
) -> CollectionRunListResponse:
    query = search.strip() if search else ""
    filters = []
    if status != "all":
        filters.append(CollectionRun.status == status)
    if ownership != "all":
        filters.append(Competitor.ownership == ownership)
    if query:
        pattern = f"%{query.lower()}%"
        filters.append(or_(
            func.lower(Competitor.title).like(pattern),
            func.lower(Competitor.offer_id).like(pattern),
            func.lower(Competitor.shop_name).like(pattern),
        ))

    base = select(CollectionRun, Competitor).join(Competitor)
    if filters:
        base = base.where(*filters)
    total = db.scalar(select(func.count()).select_from(CollectionRun).join(Competitor).where(*filters)) or 0
    rows = db.execute(
        base.order_by(CollectionRun.started_at.desc(), CollectionRun.id.desc())
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
    ).all()
    return CollectionRunListResponse(
        items=[
            CollectionRunItemResponse(
                id=run.id,
                competitor_id=run.competitor_id,
                ownership=competitor.ownership,
                title=competitor.title,
                offer_id=competitor.offer_id,
                shop_name=competitor.shop_name,
                started_at=run.started_at,
                finished_at=run.finished_at,
                status=run.status,
                error_type=run.error_type,
                error_message=run.error_message,
                duration_seconds=_duration_seconds(run),
            )
            for run, competitor in rows
        ],
        total=total,
        page=page,
        page_size=PAGE_SIZE,
    )
