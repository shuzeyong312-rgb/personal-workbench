from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.competitor_detail import _display_sku_name
from app.competitors import _price_text, error
from app.dashboard import business_date_utc_bounds, business_day_bounds
from app.database import get_db
from app.models import ChangeEvent, Competitor, CompetitorGroup, ProductSnapshot, SkuSnapshot


router = APIRouter(prefix="/api/competitor-groups", tags=["group-detail"])

_EVENT_DOMAIN = {
    "price_increase": "price",
    "price_decrease": "price",
    "stock_increase": "stock",
    "stock_decrease": "stock",
    "sku_sold_out": "stock",
    "sku_restocked": "stock",
    "stock_changed": "stock",
    "sku_added": "sku",
    "sku_removed": "sku",
    "min_order_quantity_increase": "min_order_quantity",
    "min_order_quantity_decrease": "min_order_quantity",
    "product_offline": "lifecycle",
    "product_online": "lifecycle",
    "title_changed": "title",
    "main_image_changed": "main_image",
}
_DOMAINS = ("price", "stock", "sku", "min_order_quantity", "lifecycle", "title", "main_image")


class GroupResponse(BaseModel):
    id: int
    name: str
    created_at: datetime


class LatestSnapshotResponse(BaseModel):
    id: int
    captured_at: datetime
    price_min: str | None
    price_max: str | None
    min_order_quantity: int | None
    sku_count: int
    total_stock: int | None


class ChangeResponse(BaseModel):
    id: int
    snapshot_id: int | None
    collection_run_id: int | None
    change_type: str
    entity_key: str | None
    old_value: str | None
    new_value: str | None
    delta_value: str | None
    delta_rate: str | None
    detected_at: datetime
    sku_name: str | None


class ProductFactsResponse(BaseModel):
    id: int
    role: Literal["own", "competitor"]
    platform: str
    offer_id: str
    url: str
    title: str | None
    shop_name: str | None
    main_image_url: str | None
    status: str
    is_active: bool
    last_collected_at: datetime | None
    latest_snapshot: LatestSnapshotResponse | None
    latest_change: ChangeResponse | None


class ComparisonResponse(BaseModel):
    price: Literal["lower", "higher", "overlap", "unknown"]
    min_order_quantity: Literal["lower", "higher", "equal", "unknown"]
    sku_count: Literal["more", "fewer", "equal", "unknown"]
    total_stock: Literal["higher", "lower", "equal", "unknown"]


class CompetitorResponse(ProductFactsResponse):
    comparison: ComparisonResponse


class FactGapMetricResponse(BaseModel):
    matched_count: int
    comparable_count: int


class SummaryResponse(BaseModel):
    direct_competitor_count: int
    monitored_competitor_count: int
    changed_competitors_today: int
    price_lower_than_own: FactGapMetricResponse
    moq_lower_than_own: FactGapMetricResponse
    sku_more_than_own: FactGapMetricResponse
    stock_higher_than_own: FactGapMetricResponse


class GroupEventResponse(ChangeResponse):
    competitor_id: int
    role: Literal["own", "competitor"]
    title: str | None
    offer_id: str


class TodayResponse(BaseModel):
    own_event_count: int
    competitor_event_count: int
    changed_competitor_count: int
    events: list[GroupEventResponse]


class ActionDomainCountsResponse(BaseModel):
    price: int
    stock: int
    sku: int
    min_order_quantity: int
    lifecycle: int
    title: int
    main_image: int


class ActionCompetitorResponse(BaseModel):
    competitor_id: int
    title: str | None
    offer_id: str
    event_count: int
    latest_change_at: datetime
    domain_counts: ActionDomainCountsResponse


class ActionWindowResponse(BaseModel):
    days: int
    own_event_count: int
    competitor_event_count: int
    competitors: list[ActionCompetitorResponse]


class GroupDetailResponse(BaseModel):
    range_days: int
    group: GroupResponse
    own_product: ProductFactsResponse | None
    summary: SummaryResponse
    competitors: list[CompetitorResponse]
    today: TodayResponse
    action_window: ActionWindowResponse


def _latest_snapshots(db: Session, competitor_ids: list[int]) -> dict[int, ProductSnapshot]:
    if not competitor_ids:
        return {}
    ranked = (
        select(
            ProductSnapshot.id.label("snapshot_id"),
            ProductSnapshot.competitor_id.label("competitor_id"),
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
    snapshots = db.scalars(
        select(ProductSnapshot)
        .join(ranked, ranked.c.snapshot_id == ProductSnapshot.id)
        .where(ranked.c.snapshot_rank == 1)
    ).all()
    return {snapshot.competitor_id: snapshot for snapshot in snapshots}


def _latest_changes(db: Session, competitor_ids: list[int]) -> dict[int, ChangeEvent]:
    if not competitor_ids:
        return {}
    ranked = (
        select(
            ChangeEvent.id.label("event_id"),
            ChangeEvent.competitor_id.label("competitor_id"),
            func.row_number()
            .over(
                partition_by=ChangeEvent.competitor_id,
                order_by=(ChangeEvent.detected_at.desc(), ChangeEvent.id.desc()),
            )
            .label("event_rank"),
        )
        .where(ChangeEvent.competitor_id.in_(competitor_ids))
        .subquery()
    )
    changes = db.scalars(
        select(ChangeEvent)
        .join(ranked, ranked.c.event_id == ChangeEvent.id)
        .where(ranked.c.event_rank == 1)
    ).all()
    return {change.competitor_id: change for change in changes}


def _sku_names(
    db: Session,
    events: list[ChangeEvent],
    competitor_ids: list[int],
) -> dict[tuple[int | None, str], str | None]:
    sku_events = [event for event in events if event.entity_key]
    if not sku_events:
        return {}

    sku_ids = {event.entity_key for event in sku_events if event.entity_key is not None}
    snapshot_ids = {event.snapshot_id for event in sku_events if event.snapshot_id is not None}
    exact_names: dict[tuple[int, str], str] = {}
    if snapshot_ids:
        rows = db.execute(
            select(SkuSnapshot.product_snapshot_id, SkuSnapshot.sku_id, SkuSnapshot.sku_name).where(
                SkuSnapshot.product_snapshot_id.in_(snapshot_ids),
                SkuSnapshot.sku_id.in_(sku_ids),
            )
        ).all()
        for snapshot_id, sku_id, sku_name in rows:
            name = _display_sku_name(sku_name)
            if name is not None:
                exact_names[(snapshot_id, sku_id)] = name

    historical_names: dict[tuple[int, str], str] = {}
    rows = db.execute(
        select(
            ProductSnapshot.competitor_id,
            SkuSnapshot.sku_id,
            SkuSnapshot.sku_name,
        )
        .join(ProductSnapshot, ProductSnapshot.id == SkuSnapshot.product_snapshot_id)
        .where(
            ProductSnapshot.competitor_id.in_(competitor_ids),
            SkuSnapshot.sku_id.in_(sku_ids),
        )
        .order_by(
            ProductSnapshot.competitor_id.asc(),
            SkuSnapshot.sku_id.asc(),
            ProductSnapshot.captured_at.desc(),
            ProductSnapshot.id.desc(),
            SkuSnapshot.id.desc(),
        )
    ).all()
    for competitor_id, sku_id, sku_name in rows:
        key = (competitor_id, sku_id)
        if key not in historical_names:
            name = _display_sku_name(sku_name)
            if name is not None:
                historical_names[key] = name

    result: dict[tuple[int | None, str], str | None] = {}
    for event in sku_events:
        assert event.entity_key is not None
        result[(event.id, event.entity_key)] = exact_names.get(
            (event.snapshot_id, event.entity_key)
        ) or historical_names.get((event.competitor_id, event.entity_key))
    return result


def _change_payload(
    event: ChangeEvent | None,
    sku_names: dict[tuple[int | None, str], str | None],
) -> dict[str, object] | None:
    if event is None:
        return None
    return {
        "id": event.id,
        "snapshot_id": event.snapshot_id,
        "collection_run_id": event.collection_run_id,
        "change_type": event.change_type,
        "entity_key": event.entity_key,
        "old_value": event.old_value,
        "new_value": event.new_value,
        "delta_value": str(event.delta_value) if event.delta_value is not None else None,
        "delta_rate": str(event.delta_rate) if event.delta_rate is not None else None,
        "detected_at": event.detected_at,
        "sku_name": sku_names.get((event.id, event.entity_key)) if event.entity_key else None,
    }


def _total_stock(skus: list[SkuSnapshot]) -> int | None:
    if not skus or any(sku.stock is None or sku.stock < 0 for sku in skus):
        return None
    return sum(sku.stock for sku in skus if sku.stock is not None)


def _product_facts(
    competitor: Competitor,
    latest_snapshot: ProductSnapshot | None,
    skus: list[SkuSnapshot],
    latest_change: ChangeEvent | None,
    sku_names: dict[tuple[int | None, str], str | None],
) -> dict[str, object]:
    return {
        "id": competitor.id,
        "role": competitor.group_role,
        "platform": competitor.platform,
        "offer_id": competitor.offer_id,
        "url": competitor.url,
        "title": competitor.title,
        "shop_name": competitor.shop_name,
        "main_image_url": competitor.main_image_url,
        "status": competitor.status,
        "is_active": competitor.is_active,
        "last_collected_at": competitor.last_collected_at,
        "latest_snapshot": (
            {
                "id": latest_snapshot.id,
                "captured_at": latest_snapshot.captured_at,
                "price_min": _price_text(latest_snapshot.price_min),
                "price_max": _price_text(latest_snapshot.price_max),
                "min_order_quantity": latest_snapshot.min_order_quantity,
                "sku_count": len(skus),
                "total_stock": _total_stock(skus),
            }
            if latest_snapshot is not None
            else None
        ),
        "latest_change": _change_payload(latest_change, sku_names),
    }


def _comparison(
    own: dict[str, object] | None,
    competitor: dict[str, object],
) -> dict[str, str]:
    unknown = {
        "price": "unknown",
        "min_order_quantity": "unknown",
        "sku_count": "unknown",
        "total_stock": "unknown",
    }
    if own is None:
        return unknown

    own_snapshot = own["latest_snapshot"]
    competitor_snapshot = competitor["latest_snapshot"]
    if not isinstance(own_snapshot, dict) or not isinstance(competitor_snapshot, dict):
        price = "unknown"
    elif any(
        snapshot[field] is None
        for snapshot in (own_snapshot, competitor_snapshot)
        for field in ("price_min", "price_max")
    ):
        price = "unknown"
    elif Decimal(str(competitor_snapshot["price_max"])) < Decimal(str(own_snapshot["price_min"])):
        price = "lower"
    elif Decimal(str(competitor_snapshot["price_min"])) > Decimal(str(own_snapshot["price_max"])):
        price = "higher"
    else:
        price = "overlap"

    moq = "unknown"
    if isinstance(own_snapshot, dict) and isinstance(competitor_snapshot, dict):
        own_moq = own_snapshot["min_order_quantity"]
        competitor_moq = competitor_snapshot["min_order_quantity"]
        if own_moq is not None and competitor_moq is not None:
            moq = "lower" if competitor_moq < own_moq else "higher" if competitor_moq > own_moq else "equal"

    sku_count = "unknown"
    stock = "unknown"
    if isinstance(own_snapshot, dict) and isinstance(competitor_snapshot, dict):
        own_count, competitor_count = own_snapshot["sku_count"], competitor_snapshot["sku_count"]
        sku_count = "more" if competitor_count > own_count else "fewer" if competitor_count < own_count else "equal"
        own_stock, competitor_stock = own_snapshot["total_stock"], competitor_snapshot["total_stock"]
        if own_stock is not None and competitor_stock is not None:
            stock = "higher" if competitor_stock > own_stock else "lower" if competitor_stock < own_stock else "equal"

    return {
        "price": price,
        "min_order_quantity": moq,
        "sku_count": sku_count,
        "total_stock": stock,
    }


def _event_domain(change_type: str) -> str:
    return _EVENT_DOMAIN[change_type]


@router.get("/{group_id}/detail", response_model=GroupDetailResponse)
def get_group_detail(
    group_id: int,
    days: int = Query(default=7, ge=7, le=30),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    if days not in (7, 30):
        raise HTTPException(status_code=422, detail="days must be 7 or 30")
    return _build_group_detail(db, group_id, days)


def _build_group_detail(db: Session, group_id: int, days: int) -> dict[str, object]:
    group = db.get(CompetitorGroup, group_id)
    if group is None:
        raise error("competitor_group_not_found", "竞品组不存在", status.HTTP_404_NOT_FOUND)

    members = list(
        db.scalars(
            select(Competitor)
            .where(Competitor.group_id == group_id)
            .order_by(Competitor.id.asc())
        ).all()
    )
    member_ids = [member.id for member in members]
    member_by_id = {member.id: member for member in members}
    own_member = next((member for member in members if member.group_role == "own"), None)
    direct_members = [member for member in members if member.group_role == "competitor"]

    snapshots = _latest_snapshots(db, member_ids)
    snapshot_ids = [snapshot.id for snapshot in snapshots.values()]
    skus_by_snapshot: defaultdict[int, list[SkuSnapshot]] = defaultdict(list)
    if snapshot_ids:
        for sku in db.scalars(
            select(SkuSnapshot)
            .where(SkuSnapshot.product_snapshot_id.in_(snapshot_ids))
            .order_by(SkuSnapshot.product_snapshot_id.asc(), SkuSnapshot.id.asc())
        ).all():
            skus_by_snapshot[sku.product_snapshot_id].append(sku)

    latest_changes = _latest_changes(db, member_ids)
    current_date, today_start_utc, today_end_utc = business_day_bounds()
    first_date = current_date - timedelta(days=days - 1)
    window_start_utc, _ = business_date_utc_bounds(first_date)
    period_events = list(
        db.scalars(
            select(ChangeEvent)
            .where(
                ChangeEvent.competitor_id.in_(member_ids),
                ChangeEvent.detected_at >= window_start_utc,
                ChangeEvent.detected_at < today_end_utc,
            )
            .order_by(ChangeEvent.detected_at.desc(), ChangeEvent.id.desc())
        ).all()
    ) if member_ids else []
    today_events = [event for event in period_events if event.detected_at >= today_start_utc]
    all_display_events = list({event.id: event for event in [*period_events, *latest_changes.values()]}.values())
    sku_names = _sku_names(db, all_display_events, member_ids)

    facts_by_id: dict[int, dict[str, object]] = {}
    for member in members:
        snapshot = snapshots.get(member.id)
        facts_by_id[member.id] = _product_facts(
            member,
            snapshot,
            skus_by_snapshot.get(snapshot.id, []) if snapshot is not None else [],
            latest_changes.get(member.id),
            sku_names,
        )

    own_facts = facts_by_id.get(own_member.id) if own_member is not None else None
    competitors = []
    fact_metrics = {
        "price_lower_than_own": ["price", "lower"],
        "moq_lower_than_own": ["min_order_quantity", "lower"],
        "sku_more_than_own": ["sku_count", "more"],
        "stock_higher_than_own": ["total_stock", "higher"],
    }
    matched = {key: 0 for key in fact_metrics}
    comparable = {key: 0 for key in fact_metrics}
    for member in direct_members:
        facts = facts_by_id[member.id]
        comparison = _comparison(own_facts, facts)
        facts["comparison"] = comparison
        competitors.append(facts)
        for key, (field, expected) in fact_metrics.items():
            value = comparison[field]
            if value != "unknown":
                comparable[key] += 1
                if value == expected:
                    matched[key] += 1

    changed_competitor_ids = {
        event.competitor_id
        for event in today_events
        if member_by_id[event.competitor_id].group_role == "competitor"
    }
    today_payload = []
    for event in today_events:
        member = member_by_id[event.competitor_id]
        today_payload.append(
            {
                **(_change_payload(event, sku_names) or {}),
                "competitor_id": member.id,
                "role": member.group_role,
                "title": member.title,
                "offer_id": member.offer_id,
            }
        )

    action_by_id: dict[int, dict[str, object]] = {}
    own_event_count = 0
    competitor_event_count = 0
    for event in period_events:
        member = member_by_id[event.competitor_id]
        if member.group_role == "own":
            own_event_count += 1
            continue
        competitor_event_count += 1
        item = action_by_id.setdefault(
            member.id,
            {
                "competitor_id": member.id,
                "title": member.title,
                "offer_id": member.offer_id,
                "event_count": 0,
                "latest_change_at": event.detected_at,
                "domain_counts": {domain: 0 for domain in _DOMAINS},
            },
        )
        item["event_count"] = int(item["event_count"]) + 1
        domain_counts = item["domain_counts"]
        assert isinstance(domain_counts, dict)
        domain = _event_domain(event.change_type)
        domain_counts[domain] = int(domain_counts[domain]) + 1

    action_items = sorted(
        action_by_id.values(),
        key=lambda item: (-int(item["event_count"]), -item["latest_change_at"].timestamp(), int(item["competitor_id"])),
    )

    return {
        "range_days": days,
        "group": group,
        "own_product": own_facts,
        "summary": {
            "direct_competitor_count": len(direct_members),
            "monitored_competitor_count": sum(member.is_active for member in direct_members),
            "changed_competitors_today": len(changed_competitor_ids),
            **{
                key: {"matched_count": matched[key], "comparable_count": comparable[key]}
                for key in fact_metrics
            },
        },
        "competitors": competitors,
        "today": {
            "own_event_count": sum(
                member_by_id[event.competitor_id].group_role == "own" for event in today_events
            ),
            "competitor_event_count": sum(
                member_by_id[event.competitor_id].group_role == "competitor" for event in today_events
            ),
            "changed_competitor_count": len(changed_competitor_ids),
            "events": today_payload,
        },
        "action_window": {
            "days": days,
            "own_event_count": own_event_count,
            "competitor_event_count": competitor_event_count,
            "competitors": action_items,
        },
    }
