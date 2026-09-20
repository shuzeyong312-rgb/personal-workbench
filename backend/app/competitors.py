import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.collection.service import (
    CollectionError,
    CollectionInProgressError,
    CompetitorNotFoundError,
    CollectionResult,
    COLLECTION_LOCK,
    collect_competitor,
)
from app.database import get_db
from app.models import ChangeEvent, CollectionRun, Competitor, CompetitorGroup, ProductSnapshot, SkuSnapshot


router = APIRouter(prefix="/api/competitors", tags=["competitors"])
OFFER_PATH = re.compile(r"^/offer/(\d+)\.html$")


class CreateCompetitorRequest(BaseModel):
    url: str
    group_id: int | None = None


class MonitoringRequest(BaseModel):
    is_active: bool


class CompetitorResponse(BaseModel):
    id: int
    platform: str
    offer_id: str
    url: str
    group_id: int | None
    status: str
    is_active: bool
    created_at: datetime


class LatestSnapshotResponse(BaseModel):
    price_min: str | None
    price_max: str | None
    sku_count: int


class ChangeEventSummary(BaseModel):
    id: int
    snapshot_id: int
    change_type: str
    entity_key: str | None
    old_value: str | None
    new_value: str | None
    detected_at: datetime


class CompetitorListResponse(BaseModel):
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
    latest_snapshot: "LatestSnapshotResponse | None"
    latest_change: ChangeEventSummary | None


class SnapshotResponse(BaseModel):
    id: int
    competitor_id: int
    captured_at: datetime
    title: str
    shop_name: str
    main_image_url: str | None
    price_min: str | None
    price_max: str | None
    product_status: str
    collection_source: str
    sku_count: int


class CollectionRunResponse(BaseModel):
    id: int
    competitor_id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    error_type: str | None
    error_message: str | None


class CollectCompetitorResponse(BaseModel):
    competitor: CompetitorListResponse
    snapshot: SnapshotResponse
    collection_run: CollectionRunResponse


def parse_1688_url(url: str) -> tuple[str, str]:
    value = url.strip()
    if not value:
        raise ValueError("invalid competitor url")

    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "detail.1688.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
    ):
        raise ValueError("invalid competitor url")

    match = OFFER_PATH.fullmatch(parsed.path)
    if not match:
        raise ValueError("invalid competitor url")

    offer_id = match.group(1)
    return offer_id, f"https://detail.1688.com/offer/{offer_id}.html"


def error(code: str, message: str, status_code: int) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _price_text(value: object) -> str | None:
    if value is None:
        return None
    return f"{value:.2f}"


def _latest_snapshots(db: Session, competitor_ids: list[int]) -> dict[int, LatestSnapshotResponse]:
    if not competitor_ids:
        return {}

    ranked = (
        select(
            ProductSnapshot.id.label("snapshot_id"),
            ProductSnapshot.competitor_id,
            ProductSnapshot.price_min,
            ProductSnapshot.price_max,
            func.row_number()
            .over(
                partition_by=ProductSnapshot.competitor_id,
                order_by=(ProductSnapshot.captured_at.desc(), ProductSnapshot.id.desc()),
            )
            .label("snapshot_rank"),
        )
        .where(ProductSnapshot.competitor_id.in_(competitor_ids))
        .subquery()
    )
    rows = db.execute(
        select(
            ranked.c.competitor_id,
            ranked.c.price_min,
            ranked.c.price_max,
            func.count(SkuSnapshot.id).label("sku_count"),
        )
        .outerjoin(SkuSnapshot, SkuSnapshot.product_snapshot_id == ranked.c.snapshot_id)
        .where(ranked.c.snapshot_rank == 1)
        .group_by(
            ranked.c.competitor_id,
            ranked.c.snapshot_id,
            ranked.c.price_min,
            ranked.c.price_max,
        )
    ).all()
    return {
        int(row.competitor_id): LatestSnapshotResponse(
            price_min=_price_text(row.price_min),
            price_max=_price_text(row.price_max),
            sku_count=int(row.sku_count),
        )
        for row in rows
    }


def _latest_changes(db: Session, competitor_ids: list[int]) -> dict[int, ChangeEventSummary]:
    if not competitor_ids:
        return {}

    ranked = (
        select(
            ChangeEvent.id,
            ChangeEvent.competitor_id,
            ChangeEvent.snapshot_id,
            ChangeEvent.change_type,
            ChangeEvent.entity_key,
            ChangeEvent.old_value,
            ChangeEvent.new_value,
            ChangeEvent.detected_at,
            func.row_number()
            .over(
                partition_by=ChangeEvent.competitor_id,
                order_by=(ChangeEvent.detected_at.desc(), ChangeEvent.id.desc()),
            )
            .label("change_rank"),
        )
        .where(ChangeEvent.competitor_id.in_(competitor_ids))
        .subquery()
    )
    rows = db.execute(
        select(
            ranked.c.id,
            ranked.c.competitor_id,
            ranked.c.snapshot_id,
            ranked.c.change_type,
            ranked.c.entity_key,
            ranked.c.old_value,
            ranked.c.new_value,
            ranked.c.detected_at,
        ).where(ranked.c.change_rank == 1)
    ).all()
    return {
        int(row.competitor_id): ChangeEventSummary(
            id=int(row.id),
            snapshot_id=int(row.snapshot_id),
            change_type=row.change_type,
            entity_key=row.entity_key,
            old_value=row.old_value,
            new_value=row.new_value,
            detected_at=row.detected_at,
        )
        for row in rows
    }


def _competitor_payload(
    competitor: Competitor,
    latest_snapshot: LatestSnapshotResponse | None,
    latest_change: ChangeEventSummary | None,
) -> dict[str, object]:
    return {
        "id": competitor.id,
        "platform": competitor.platform,
        "offer_id": competitor.offer_id,
        "url": competitor.url,
        "group_id": competitor.group_id,
        "title": competitor.title,
        "shop_name": competitor.shop_name,
        "main_image_url": competitor.main_image_url,
        "status": competitor.status,
        "is_active": competitor.is_active,
        "created_at": competitor.created_at,
        "last_collected_at": competitor.last_collected_at,
        "latest_snapshot": latest_snapshot,
        "latest_change": latest_change,
    }


def _snapshot_payload(result: CollectionResult) -> dict[str, object]:
    snapshot = result.snapshot
    return {
        "id": snapshot.id,
        "competitor_id": snapshot.competitor_id,
        "captured_at": snapshot.captured_at,
        "title": snapshot.title,
        "shop_name": snapshot.shop_name,
        "main_image_url": snapshot.main_image_url,
        "price_min": _price_text(snapshot.price_min),
        "price_max": _price_text(snapshot.price_max),
        "product_status": snapshot.product_status,
        "collection_source": snapshot.collection_source,
        "sku_count": result.sku_count,
    }


def _collection_run_payload(result: CollectionResult) -> dict[str, object]:
    run = result.collection_run
    return {
        "id": run.id,
        "competitor_id": run.competitor_id,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "status": run.status,
        "error_type": run.error_type,
        "error_message": run.error_message,
    }


@router.get("", response_model=list[CompetitorListResponse])
def list_competitors(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    competitors = list(
        db.scalars(
            select(Competitor).order_by(
                Competitor.created_at.desc(),
                Competitor.id.desc(),
            )
        ).all()
    )
    latest_by_competitor = _latest_snapshots(db, [competitor.id for competitor in competitors])
    latest_change_by_competitor = _latest_changes(db, [competitor.id for competitor in competitors])
    return [
        _competitor_payload(
            competitor,
            latest_by_competitor.get(competitor.id),
            latest_change_by_competitor.get(competitor.id),
        )
        for competitor in competitors
    ]


@router.post("", response_model=CompetitorResponse, status_code=status.HTTP_201_CREATED)
def create_competitor(payload: CreateCompetitorRequest, db: Session = Depends(get_db)) -> Competitor:
    try:
        offer_id, normalized_url = parse_1688_url(payload.url)
    except ValueError as exc:
        raise error(
            "invalid_competitor_url",
            "仅支持 https://detail.1688.com/offer/{offerId}.html 格式的 1688 商品链接",
            status.HTTP_400_BAD_REQUEST,
        ) from exc

    if payload.group_id is not None and db.get(CompetitorGroup, payload.group_id) is None:
        raise error("competitor_group_not_found", "竞品组不存在", status.HTTP_404_NOT_FOUND)

    if db.scalar(select(Competitor).where(Competitor.platform == "1688", Competitor.offer_id == offer_id)):
        raise error("competitor_already_exists", "该 1688 商品已经添加", status.HTTP_409_CONFLICT)

    now = datetime.now(timezone.utc)
    competitor = Competitor(
        platform="1688",
        offer_id=offer_id,
        url=normalized_url,
        group_id=payload.group_id,
        status="unknown",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(competitor)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(Competitor).where(
                Competitor.platform == "1688",
                Competitor.offer_id == offer_id,
            )
        )
        if existing:
            raise error("competitor_already_exists", "该 1688 商品已经添加", status.HTTP_409_CONFLICT)
        raise
    db.refresh(competitor)
    return competitor


@router.patch("/{competitor_id}/monitoring", response_model=CompetitorResponse)
def update_monitoring(
    competitor_id: int,
    payload: MonitoringRequest,
    db: Session = Depends(get_db),
) -> Competitor:
    competitor = db.get(Competitor, competitor_id)
    if competitor is None:
        raise error("competitor_not_found", "竞品不存在", status.HTTP_404_NOT_FOUND)

    competitor.is_active = payload.is_active
    competitor.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(competitor)
    return competitor


@router.delete("/{competitor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_competitor(competitor_id: int, db: Session = Depends(get_db)) -> None:
    if db.get(Competitor, competitor_id) is None:
        raise error("competitor_not_found", "竞品不存在", status.HTTP_404_NOT_FOUND)
    if not COLLECTION_LOCK.acquire(blocking=False):
        raise error(
            "collection_in_progress",
            "已有竞品正在采集，请稍后重试",
            status.HTTP_409_CONFLICT,
        )

    try:
        competitor = db.get(Competitor, competitor_id)
        if competitor is None:
            raise error("competitor_not_found", "竞品不存在", status.HTTP_404_NOT_FOUND)
        snapshot_ids = select(ProductSnapshot.id).where(ProductSnapshot.competitor_id == competitor_id)
        db.execute(delete(ChangeEvent).where(ChangeEvent.competitor_id == competitor_id))
        db.execute(delete(CollectionRun).where(CollectionRun.competitor_id == competitor_id))
        db.execute(delete(SkuSnapshot).where(SkuSnapshot.product_snapshot_id.in_(snapshot_ids)))
        db.execute(delete(ProductSnapshot).where(ProductSnapshot.competitor_id == competitor_id))
        db.delete(competitor)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise error(
            "competitor_delete_failed",
            "竞品删除失败，请稍后重试",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        ) from exc
    finally:
        COLLECTION_LOCK.release()


_COLLECTION_STATUS_CODES = {
    "competitor_inactive": status.HTTP_409_CONFLICT,
    "1688_login_required": status.HTTP_401_UNAUTHORIZED,
    "1688_verification_required": status.HTTP_403_FORBIDDEN,
    "1688_page_unavailable": status.HTTP_502_BAD_GATEWAY,
    "collection_timeout": status.HTTP_504_GATEWAY_TIMEOUT,
    "collection_parse_failed": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "collection_partial_data": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "offer_id_mismatch": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "collection_save_failed": status.HTTP_500_INTERNAL_SERVER_ERROR,
    "collection_failed": status.HTTP_500_INTERNAL_SERVER_ERROR,
}


@router.post("/{competitor_id}/collect", response_model=CollectCompetitorResponse)
def collect_competitor_now(
    competitor_id: int,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        result = collect_competitor(db, competitor_id)
    except CompetitorNotFoundError as exc:
        raise error("competitor_not_found", "竞品不存在", status.HTTP_404_NOT_FOUND) from exc
    except CollectionInProgressError as exc:
        raise error(
            "collection_in_progress",
            "已有竞品正在采集，请稍后重试",
            status.HTTP_409_CONFLICT,
        ) from exc
    except CollectionError as exc:
        raise error(
            exc.code,
            exc.message,
            _COLLECTION_STATUS_CODES.get(exc.code, status.HTTP_500_INTERNAL_SERVER_ERROR),
        ) from exc

    latest_snapshot = LatestSnapshotResponse(
        price_min=_price_text(result.snapshot.price_min),
        price_max=_price_text(result.snapshot.price_max),
        sku_count=result.sku_count,
    )
    latest_change = _latest_changes(db, [result.competitor.id]).get(result.competitor.id)
    return {
        "competitor": _competitor_payload(result.competitor, latest_snapshot, latest_change),
        "snapshot": _snapshot_payload(result),
        "collection_run": _collection_run_payload(result),
    }
