from collections import defaultdict, Counter
import base64
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select, and_, or_
from sqlalchemy.orm import Session

from app.competitor_detail import _display_sku_name
from app.competitors import _price_text, error
from app.dashboard import business_date_utc_bounds, business_day_bounds
from app.database import get_db
from app.models import ChangeEvent, Competitor, CompetitorGroup, ProductSnapshot, SkuSnapshot
from app.operating_metrics import OPERATING_METRICS, load_operating_metrics


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
    latest_collection_run: dict[str, object] | None
    operating_metrics: list[dict[str, object]]


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
    shop_name: str | None


class EventPageResponse(BaseModel):
    items: list[GroupEventResponse]
    has_more: bool
    next_cursor: str | None
    range: Literal["today", "7", "30"]
    mode: Literal["important", "all"]
    limit: int
    window_start: datetime
    window_end: datetime
    through_event_id: int
    important_offer_ids: list[int]


class OfferPositionResponse(BaseModel):
    eligible: bool
    reason: str | None
    sort_value: str | int | None
    rank_asc: int | None
    rank_desc: int | None


class MetricPositionResponse(BaseModel):
    default_direction: Literal["asc", "desc"]
    group_count: int
    eligible_count: int
    offers: dict[int, OfferPositionResponse]


class TodayResponse(BaseModel):
    own_event_count: int
    competitor_event_count: int
    changed_competitor_count: int
    events: list[GroupEventResponse]
    event_pagination: EventPageResponse
    important_offer_ids: list[int]


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
    important_offer_ids: list[int]


class GroupDetailResponse(BaseModel):
    range_days: int
    group: GroupResponse
    own_product: ProductFactsResponse | None
    summary: SummaryResponse
    competitors: list[CompetitorResponse]
    today: TodayResponse
    action_window: ActionWindowResponse
    position: dict[str, MetricPositionResponse]
    event_page: EventPageResponse
    operating_metrics_coverage: dict[str, dict[str, int]]


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
        select(ProductSnapshot.competitor_id, SkuSnapshot.sku_id, SkuSnapshot.sku_name)
        .join(ProductSnapshot, ProductSnapshot.id == SkuSnapshot.product_snapshot_id)
        .where(ProductSnapshot.competitor_id.in_(competitor_ids), SkuSnapshot.sku_id.in_(sku_ids))
        .order_by(ProductSnapshot.captured_at.desc(), ProductSnapshot.id.desc(), SkuSnapshot.id.desc())
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
        "role": "own" if competitor.ownership == "self" else "competitor",
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


_IMPORTANT_TYPES = tuple(k for k, v in _EVENT_DOMAIN.items() if v in ("price", "sku", "min_order_quantity"))


def _positions(facts: list[dict]) -> dict:
    result = {}
    for key, field, direction in (("display_price_min", "price_min", "asc"), ("min_order_quantity", "min_order_quantity", "asc"), ("sku_count", "sku_count", "desc"), ("total_stock", "total_stock", "desc")):
        offers, values = {}, {}
        for fact in facts:
            snap = fact["latest_snapshot"]
            reason = "not_monitored" if not fact["is_active"] else "offline" if fact["status"] == "offline" else "status_unknown" if fact["status"] != "active" else "no_snapshot" if snap is None else None
            value = snap[field] if snap else None
            if reason is None:
                if key == "display_price_min":
                    high = snap["price_max"]
                    if value is None or high is None or not Decimal(value).is_finite() or not Decimal(high).is_finite() or Decimal(value) < 0 or Decimal(value) > Decimal(high):
                        reason = "unknown_value"
                elif value is None or value < (1 if key == "min_order_quantity" else 0):
                    reason = "unknown_value"
            offers[fact["id"]] = dict(eligible=reason is None, reason=reason, sort_value=value if reason is None else None, rank_asc=None, rank_desc=None)
            if reason is None:
                values[fact["id"]] = Decimal(value) if key == "display_price_min" else value
        counts, asc, desc, before = Counter(values.values()), {}, {}, 0
        for value in sorted(counts):
            asc[value] = before + 1
            before += counts[value]
            desc[value] = len(values) - before + 1
        for id_, value in values.items():
            offers[id_].update(rank_asc=asc[value], rank_desc=desc[value])
        result[key] = dict(default_direction=direction, group_count=len(facts), eligible_count=len(values), offers=offers)
    return result


def _event_context(db: Session, members: list[Competitor], group_id: int, range_: str, mode: str, limit: int, cursor: str | None = None) -> dict:
    identity = [[m.id, m.ownership, m.group_role] for m in members]
    expected = dict(group=group_id, range=range_, mode=mode, limit=limit)
    if cursor is not None:
        try:
            if len(cursor) > 100000:
                raise ValueError()
            ctx = json.loads(base64.b64decode(cursor.encode(), altchars=b"-_", validate=True))
            if not isinstance(ctx, dict) or any(ctx.get(k) != v or type(ctx.get(k)) is not type(v) for k, v in expected.items()):
                raise ValueError()
            stamps = [datetime.fromisoformat(ctx[k]) for k in ("start", "end", "last_time")]
            start, end, last = stamps
            if start.hour != 16 or any((start.minute, start.second, start.microsecond, end.minute, end.second, end.microsecond)) or any(t.tzinfo is not None for t in stamps) or end-start != timedelta(days=1 if range_ == "today" else int(range_)) or not start <= last < end:
                raise ValueError()
            if any(type(ctx[k]) is not int or not 0 <= ctx[k] <= 2**63 - 1 for k in ("through", "last_id")) or not 0 < ctx["last_id"] <= ctx["through"] or not isinstance(ctx.get("members"), list):
                raise ValueError()
            if any(not isinstance(member, list) or len(member) != 3 or type(member[0]) is not int or not 0 < member[0] <= 2**63 - 1 or member[1] not in ("self", "competitor") or member[2] not in ("own", "competitor") for member in ctx["members"]):
                raise ValueError()
        except (ValueError, TypeError, KeyError, OverflowError, UnicodeError):
            raise HTTPException(422, "invalid group event cursor")
        if ctx["members"] != identity:
            raise error("group_event_context_changed", "组成员或角色已变化，请重新加载当前历史", 409)
        return ctx
    today, _, end = business_day_bounds()
    start, _ = business_date_utc_bounds(today-timedelta(days=(1 if range_ == "today" else int(range_))-1))
    return {**expected, "members": identity, "start": start.isoformat(), "end": end.isoformat(), "through": db.scalar(select(func.max(ChangeEvent.id))) or 0}


def _event_filters(ctx: dict) -> list:
    return [ChangeEvent.competitor_id.in_([m[0] for m in ctx["members"]]), ChangeEvent.detected_at >= datetime.fromisoformat(ctx["start"]), ChangeEvent.detected_at < datetime.fromisoformat(ctx["end"]), ChangeEvent.id <= ctx["through"]]


def _event_page(db: Session, members: list[Competitor], ctx: dict, name_cache: dict | None = None) -> dict:
    filters = _event_filters(ctx)
    important_ids = list(db.scalars(select(ChangeEvent.competitor_id).where(*filters, ChangeEvent.change_type.in_(_IMPORTANT_TYPES)).distinct().order_by(ChangeEvent.competitor_id)).all())
    if ctx["mode"] == "important":
        filters.append(ChangeEvent.change_type.in_(_IMPORTANT_TYPES))
    if "last_id" in ctx:
        stamp = datetime.fromisoformat(ctx["last_time"])
        filters.append(or_(ChangeEvent.detected_at < stamp, and_(ChangeEvent.detected_at == stamp, ChangeEvent.id < ctx["last_id"])))
    events = list(db.scalars(select(ChangeEvent).where(*filters).order_by(ChangeEvent.detected_at.desc(), ChangeEvent.id.desc()).limit(ctx["limit"]+1)).all())
    more, events = len(events) > ctx["limit"], events[:ctx["limit"]]
    names = name_cache if name_cache is not None else {}
    unnamed = [event for event in events if event.entity_key and (event.id, event.entity_key) not in names]
    names.update(_sku_names(db, unnamed, list({event.competitor_id for event in unnamed})))
    by_id = {m.id: m for m in members}
    items = [{**_change_payload(e, names), "competitor_id": e.competitor_id, "role": "own" if by_id[e.competitor_id].ownership == "self" else "competitor", "title": by_id[e.competitor_id].title, "offer_id": by_id[e.competitor_id].offer_id, "shop_name": by_id[e.competitor_id].shop_name} for e in events]
    cursor = base64.urlsafe_b64encode(json.dumps({**ctx, "last_time": events[-1].detected_at.isoformat(), "last_id": events[-1].id}, separators=(",", ":")).encode()).decode() if more else None
    return dict(items=items, has_more=more, next_cursor=cursor, range=ctx["range"], mode=ctx["mode"], limit=ctx["limit"], window_start=ctx["start"], window_end=ctx["end"], through_event_id=ctx["through"], important_offer_ids=important_ids)


@router.get("/{group_id}/events", response_model=EventPageResponse)
def get_group_events(group_id: int, range_: Literal["today", "7", "30"] = Query(default="7", alias="range"), mode: Literal["important", "all"] = "important", limit: int = Query(default=20, ge=1, le=100), cursor: str | None = None, db: Session = Depends(get_db)):
    if db.get(CompetitorGroup, group_id) is None:
        raise error("competitor_group_not_found", "竞品组不存在", 404)
    members = list(db.scalars(select(Competitor).where(Competitor.group_id == group_id).order_by(Competitor.id)).all())
    return _event_page(db, members, _event_context(db, members, group_id, range_, mode, limit, cursor))


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
    own_member = next((member for member in members if member.ownership == "self" and member.group_role == "own"), None)
    direct_members = [member for member in members if member.ownership == "competitor"]

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
    operating_data = load_operating_metrics(db, member_ids)
    context = _event_context(db, members, group_id, str(days), "important", 20)
    today_context = {**context, "range": "today", "mode": "all", "start": (datetime.fromisoformat(context["end"]) - timedelta(days=1)).isoformat()}
    sku_names = {}
    event_page = _event_page(db, members, context, sku_names)
    today_page = _event_page(db, members, today_context, sku_names)
    unnamed = [event for event in latest_changes.values() if event.entity_key and (event.id, event.entity_key) not in sku_names]
    sku_names.update(_sku_names(db, unnamed, list({event.competitor_id for event in unnamed})))
    counts = db.execute(select(ChangeEvent.competitor_id, ChangeEvent.change_type, func.count(), func.max(ChangeEvent.detected_at)).where(*_event_filters(context)).group_by(ChangeEvent.competitor_id, ChangeEvent.change_type)).all()
    today_counts = dict(db.execute(select(ChangeEvent.competitor_id, func.count()).where(*_event_filters(today_context)).group_by(ChangeEvent.competitor_id)).all())

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
        facts_by_id[member.id].update(operating_data.get(member.id, {
            "latest_collection_run": None, "operating_metrics": [],
        }))

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

    changed_competitor_ids = {m.id for m in direct_members if today_counts.get(m.id, 0)}
    action_by_id = {}
    own_event_count = competitor_event_count = 0
    for member_id, change_type, count, latest_at in counts:
        member = member_by_id[member_id]
        if member.ownership == "self":
            own_event_count += count
            continue
        competitor_event_count += count
        item = action_by_id.setdefault(member_id, dict(competitor_id=member.id, title=member.title, offer_id=member.offer_id, event_count=0, latest_change_at=latest_at, domain_counts={d: 0 for d in _DOMAINS}))
        item["event_count"] += count
        item["latest_change_at"] = max(item["latest_change_at"], latest_at)
        item["domain_counts"][_event_domain(change_type)] += count

    action_items = sorted(
        action_by_id.values(),
        key=lambda item: (-int(item["event_count"]), -item["latest_change_at"].timestamp(), int(item["competitor_id"])),
    )

    return {
        "range_days": days,
        "position": _positions(([own_facts] if own_facts else []) + competitors),
        "operating_metrics_coverage": {
            key: {
                "has_history_valid_values": sum(
                    any(metric["metric_key"] == key and metric["latest_valid"] is not None
                        for metric in operating_data.get(member.id, {}).get("operating_metrics", []))
                    for member in members if member.is_active
                ),
                "active_offers": sum(member.is_active for member in members),
            }
            for key, _, _ in OPERATING_METRICS
        },
        "event_page": event_page,
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
            "own_event_count": sum(today_counts.get(m.id, 0) for m in members if m.ownership == "self"),
            "competitor_event_count": sum(today_counts.get(m.id, 0) for m in direct_members),
            "changed_competitor_count": len(changed_competitor_ids),
            "events": today_page["items"],
            "event_pagination": today_page,
            "important_offer_ids": today_page["important_offer_ids"],
        },
        "action_window": {
            "days": days,
            "own_event_count": own_event_count,
            "competitor_event_count": competitor_event_count,
            "competitors": action_items,
            "important_offer_ids": event_page["important_offer_ids"],
        },
    }
