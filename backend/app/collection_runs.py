from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.collection.batch_records import get_collection_run, list_collection_runs as query_collection_runs


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
    operating_metrics_status: str
    error_type: str | None
    error_message: str | None
    duration_seconds: float | None
    has_anomaly: bool | None = None
    collection_batch_item_id: int | None
    attempt_number: int | None
    attempt_kind: str | None
    batch_id: str | None


class CollectionRunListResponse(BaseModel):
    items: list[CollectionRunItemResponse]
    total: int
    page: int
    page_size: int


@router.get("", response_model=CollectionRunListResponse)
def list_collection_runs(
    search: str | None = None,
    status: Literal["all", "success", "failed"] = "all",
    ownership: Literal["all", "self", "competitor"] = "all",
    batch_id: str | None = None,
    anomaly: Literal["current", "none", "recovered", "all", "placeholder", "source_unavailable", "loading", "read_failed", "base_failed"] = "all",
    started_after: datetime | None = None,
    started_before: datetime | None = None,
    trigger_kind: str = "all",
    unbatched: bool = False,
    legacy_only: bool = False,
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
) -> CollectionRunListResponse:
    return CollectionRunListResponse(**query_collection_runs(
        db, search=search, status=status, ownership=ownership, batch_id=batch_id,
        anomaly=anomaly, legacy_only=unbatched or legacy_only, page=page, page_size=PAGE_SIZE,
        started_after=started_after, started_before=started_before, trigger_kind=trigger_kind,
    ))


@router.get("/{run_id}")
def collection_run_detail(run_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    run = get_collection_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "collection_run_not_found", "message": "采集记录不存在"})
    return run
