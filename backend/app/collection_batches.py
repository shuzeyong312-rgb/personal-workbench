from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.collection.batch_records import get_batch, list_batches
from app.database import get_db


router = APIRouter(prefix="/api/collection-batches", tags=["collection-batches"])
PAGE_SIZE = 20


class CollectionBatchListResponse(BaseModel):
    items: list[dict[str, object]]
    total: int
    page: int
    page_size: int


@router.get("", response_model=CollectionBatchListResponse)
def list_collection_batches(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=PAGE_SIZE, ge=1, le=100),
    trigger_kind: Literal["all", "unknown", "manual", "manual_selected", "manual_all_active", "scheduled", "manual_single", "add_links"] = "all",
    outcome: str = "all",
    search: str | None = None,
    anomaly: Literal["current", "none", "recovered", "all", "placeholder", "source_unavailable", "loading", "read_failed", "base_failed", "rejected", "verification_required"] = "all",
    started_after: datetime | None = None,
    started_before: datetime | None = None,
    db: Session = Depends(get_db),
) -> CollectionBatchListResponse:
    return CollectionBatchListResponse(**list_batches(
        db, page=page, page_size=page_size, trigger_kind=trigger_kind,
        outcome=outcome, anomaly=anomaly, started_after=started_after,
        started_before=started_before, search=search,
    ))


@router.get("/{task_id}")
def get_collection_batch(
    task_id: str, search: str | None = None,
    final_result: Literal["all", "success", "exception", "pending", "not_executed", "verification_required", "first_pass_success", "verification_resume_success", "retry_success", "final_failed", "business_rejected"] = "all",
    anomaly: Literal["all", "current", "recovered", "none", "rejected", "verification_required", "base_failed"] = "all",
    attempt_kind: Literal["all", "first_pass", "operating_metrics_retry", "verification_resume"] = "all",
    input_result: Literal["all", "added", "invalid_url", "duplicate_input", "already_exists", "identity_rejected", "technical_failed", "verification_required", "not_executed", "interrupted"] = "all",
    reason: str = "all", anomalies_first: bool = False,
    page: int = Query(default=1, ge=1), page_size: int | None = Query(default=None, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    batch = get_batch(db, task_id, search=search, final_result=final_result, anomaly=anomaly, attempt_kind=attempt_kind, reason=reason, anomalies_first=anomalies_first, page=page, page_size=page_size, input_result=input_result)
    if batch is None:
        raise HTTPException(status_code=404, detail={"code": "collection_batch_not_found", "message": "采集批次不存在"})
    return batch
