from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import and_, case, distinct, func, select, union_all, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.competitors import CompetitorResponse, error
from app.database import get_db
from app.dashboard import business_day_bounds
from app.models import ChangeEvent, Competitor, CompetitorGroup, ProductSnapshot


router = APIRouter(prefix="/api/competitor-groups", tags=["competitor-groups"])


class CreateCompetitorGroupRequest(BaseModel):
    name: str


class UpdateCompetitorGroupRequest(BaseModel):
    name: str


class CompetitorGroupResponse(BaseModel):
    id: int
    name: str
    created_at: datetime


class CompetitorGroupMetricsResponse(BaseModel):
    competitor_count: int
    active_count: int
    price_min: str | None
    price_max: str | None
    changed_competitors_today: int
    last_change_at: datetime | None


class OwnProductResponse(BaseModel):
    id: int
    offer_id: str
    title: str | None
    shop_name: str | None
    main_image_url: str | None
    status: str
    is_active: bool


class CompetitorGroupSummaryResponse(CompetitorGroupMetricsResponse):
    id: int
    name: str
    created_at: datetime
    own_product: OwnProductResponse | None


class BindOwnProductRequest(BaseModel):
    competitor_id: int
    replace_existing: bool = False


class BindOwnProductResponse(BaseModel):
    competitor: CompetitorResponse


class CompetitorGroupsSummaryResponse(BaseModel):
    groups: list[CompetitorGroupSummaryResponse]
    unassigned: CompetitorGroupMetricsResponse


def _validated_name(name: str) -> str:
    value = name.strip()
    if not value or len(value) > 64:
        raise error(
            "invalid_competitor_group_name",
            "请输入有效的商品型号",
            status.HTTP_400_BAD_REQUEST,
        )
    return value


def _price_text(value: object) -> str | None:
    if value is None:
        return None
    return f"{value:.2f}"


def _latest_price_values():
    ranked = (
        select(
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
        .subquery()
    )
    return union_all(
        select(ranked.c.competitor_id, ranked.c.price_min.label("price")).where(
            ranked.c.snapshot_rank == 1,
            ranked.c.price_min.is_not(None),
        ),
        select(ranked.c.competitor_id, ranked.c.price_max.label("price")).where(
            ranked.c.snapshot_rank == 1,
            ranked.c.price_max.is_not(None),
        ),
    ).subquery()


def _summary_rows(db: Session) -> dict[int | None, dict[str, object]]:
    _, start_utc, end_utc = business_day_bounds()
    prices = _latest_price_values()
    changed_today = distinct(
        case(
            (
                and_(
                    ChangeEvent.detected_at >= start_utc,
                    ChangeEvent.detected_at < end_utc,
                ),
                Competitor.id,
            ),
            else_=None,
        )
    )
    active_competitor = distinct(
        case((Competitor.is_active.is_(True), Competitor.id), else_=None)
    )
    rows = db.execute(
        select(
            Competitor.group_id,
            func.count(distinct(Competitor.id)).label("competitor_count"),
            func.count(active_competitor).label("active_count"),
            func.min(prices.c.price).label("price_min"),
            func.max(prices.c.price).label("price_max"),
            func.count(changed_today).label("changed_competitors_today"),
            func.max(ChangeEvent.detected_at).label("last_change_at"),
        )
        .select_from(Competitor)
        .outerjoin(prices, prices.c.competitor_id == Competitor.id)
        .outerjoin(ChangeEvent, ChangeEvent.competitor_id == Competitor.id)
        .group_by(Competitor.group_id)
        .where(Competitor.group_role == "competitor")
    ).all()
    return {
        row.group_id: {
            "competitor_count": int(row.competitor_count),
            "active_count": int(row.active_count),
            "price_min": _price_text(row.price_min),
            "price_max": _price_text(row.price_max),
            "changed_competitors_today": int(row.changed_competitors_today),
            "last_change_at": row.last_change_at,
        }
        for row in rows
    }


def _empty_metrics() -> dict[str, object]:
    return {
        "competitor_count": 0,
        "active_count": 0,
        "price_min": None,
        "price_max": None,
        "changed_competitors_today": 0,
        "last_change_at": None,
    }


def _change_sort_value(value: datetime | None) -> float:
    if value is None:
        return float("-inf")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


@router.post("", response_model=CompetitorGroupResponse, status_code=status.HTTP_201_CREATED)
def create_competitor_group(
    payload: CreateCompetitorGroupRequest, db: Session = Depends(get_db)
) -> CompetitorGroup:
    name = _validated_name(payload.name)
    group = CompetitorGroup(name=name, created_at=datetime.now(timezone.utc))
    db.add(group)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise error(
            "competitor_group_already_exists",
            "该商品型号已存在",
            status.HTTP_409_CONFLICT,
        ) from exc
    db.refresh(group)
    return group


@router.get("", response_model=list[CompetitorGroupResponse])
def list_competitor_groups(db: Session = Depends(get_db)) -> list[CompetitorGroup]:
    return list(
        db.scalars(
            select(CompetitorGroup).order_by(CompetitorGroup.created_at.asc(), CompetitorGroup.id.asc())
        ).all()
    )


@router.get("/summary", response_model=CompetitorGroupsSummaryResponse)
def summarize_competitor_groups(db: Session = Depends(get_db)) -> CompetitorGroupsSummaryResponse:
    groups = list(
        db.scalars(
            select(CompetitorGroup).order_by(CompetitorGroup.created_at.asc(), CompetitorGroup.id.asc())
        ).all()
    )
    summaries = _summary_rows(db)
    own_products = {
        competitor.group_id: OwnProductResponse(
            id=competitor.id,
            offer_id=competitor.offer_id,
            title=competitor.title,
            shop_name=competitor.shop_name,
            main_image_url=competitor.main_image_url,
            status=competitor.status,
            is_active=competitor.is_active,
        )
        for competitor in db.scalars(
            select(Competitor).where(
                Competitor.group_role == "own",
                Competitor.group_id.in_([group.id for group in groups]),
            )
        ).all()
    } if groups else {}
    group_summaries = [
        CompetitorGroupSummaryResponse(
            id=group.id,
            name=group.name,
            created_at=group.created_at,
            own_product=own_products.get(group.id),
            **summaries.get(group.id, _empty_metrics()),
        )
        for group in groups
    ]
    group_summaries.sort(key=lambda item: (item.created_at, item.id))
    group_summaries.sort(key=lambda item: item.last_change_at is None)
    group_summaries.sort(key=lambda item: _change_sort_value(item.last_change_at), reverse=True)
    return CompetitorGroupsSummaryResponse(
        groups=group_summaries,
        unassigned=CompetitorGroupMetricsResponse(**summaries.get(None, _empty_metrics())),
    )


@router.put("/{group_id}/own-product", response_model=BindOwnProductResponse)
def bind_own_product(
    group_id: int,
    payload: BindOwnProductRequest,
    db: Session = Depends(get_db),
) -> dict[str, Competitor]:
    if db.get(CompetitorGroup, group_id) is None:
        raise error("competitor_group_not_found", "竞品组不存在", status.HTTP_404_NOT_FOUND)

    competitor = db.get(Competitor, payload.competitor_id)
    if competitor is None:
        raise error("competitor_not_found", "竞品不存在", status.HTTP_404_NOT_FOUND)
    if competitor.group_id != group_id:
        raise error("competitor_not_in_group", "商品不属于该竞品组", status.HTTP_400_BAD_REQUEST)

    current_own = db.scalar(
        select(Competitor).where(
            Competitor.group_id == group_id,
            Competitor.group_role == "own",
        )
    )
    if current_own is not None and current_own.id == competitor.id:
        return {"competitor": competitor}
    if current_own is not None and not payload.replace_existing:
        raise error("own_product_already_bound", "该竞品组已绑定我方商品", status.HTTP_409_CONFLICT)

    try:
        if current_own is not None:
            db.execute(
                update(Competitor)
                .where(Competitor.id == current_own.id)
                .values(group_role="competitor", updated_at=datetime.now(timezone.utc))
            )
        db.execute(
            update(Competitor)
            .where(Competitor.id == competitor.id)
            .values(group_role="own", updated_at=datetime.now(timezone.utc))
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        concurrent_own = db.scalar(
            select(Competitor).where(
                Competitor.group_id == group_id,
                Competitor.group_role == "own",
            )
        )
        if concurrent_own is not None and concurrent_own.id != competitor.id:
            raise error(
                "own_product_already_bound",
                "该竞品组已绑定我方商品",
                status.HTTP_409_CONFLICT,
            ) from exc
        raise error(
            "own_product_bind_failed",
            "我方商品绑定失败，请稍后重试",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        ) from exc
    except Exception as exc:
        db.rollback()
        raise error(
            "own_product_bind_failed",
            "我方商品绑定失败，请稍后重试",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        ) from exc
    db.refresh(competitor)
    return {"competitor": competitor}


@router.delete("/{group_id}/own-product", status_code=status.HTTP_204_NO_CONTENT)
def unbind_own_product(group_id: int, db: Session = Depends(get_db)) -> None:
    if db.get(CompetitorGroup, group_id) is None:
        raise error("competitor_group_not_found", "竞品组不存在", status.HTTP_404_NOT_FOUND)
    try:
        db.execute(
            update(Competitor)
            .where(Competitor.group_id == group_id, Competitor.group_role == "own")
            .values(group_role="competitor", updated_at=datetime.now(timezone.utc))
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise error(
            "own_product_unbind_failed",
            "我方商品解除失败，请稍后重试",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        ) from exc


@router.patch("/{group_id}", response_model=CompetitorGroupResponse)
def update_competitor_group(
    group_id: int,
    payload: UpdateCompetitorGroupRequest,
    db: Session = Depends(get_db),
) -> CompetitorGroup:
    group = db.get(CompetitorGroup, group_id)
    if group is None:
        raise error("competitor_group_not_found", "商品型号不存在", status.HTTP_404_NOT_FOUND)

    group.name = _validated_name(payload.name)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise error(
            "competitor_group_already_exists",
            "该商品型号已存在",
            status.HTTP_409_CONFLICT,
        ) from exc
    db.refresh(group)
    return group


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_competitor_group(group_id: int, db: Session = Depends(get_db)) -> None:
    group = db.get(CompetitorGroup, group_id)
    if group is None:
        raise error("competitor_group_not_found", "商品型号不存在", status.HTTP_404_NOT_FOUND)

    try:
        db.execute(
            update(Competitor)
            .where(Competitor.group_id == group_id)
            .values(group_id=None, group_role="competitor")
        )
        db.delete(group)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise error(
            "competitor_group_delete_failed",
            "商品型号删除失败，请稍后重试",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        ) from exc
