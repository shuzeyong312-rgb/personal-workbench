from collections import defaultdict
from datetime import date, datetime, timezone
from bisect import bisect_left

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dashboard import business_day_bounds
from app.models import ChangeEvent, Competitor, CompetitorGroup, ProductSnapshot, SkuSnapshot


router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

EVENTS = {
    "price_decrease": ("S", 40, "price"), "price_increase": ("B", 12, "price"),
    "product_offline": ("A", 25, "lifecycle"), "product_online": ("B", 12, "lifecycle"),
    "sku_removed": ("A", 25, "sku"), "sku_added": ("B", 12, "sku"),
    "sku_sold_out": ("A", 25, "stock"), "sku_restocked": ("A", 25, "stock"),
    "stock_increase": ("B", 12, "stock"), "stock_decrease": ("B", 12, "stock"),
    "stock_changed": ("B", 12, "stock"),
    "min_order_quantity_decrease": ("C", 5, "moq"),
    "min_order_quantity_increase": ("C", 5, "moq"),
    "title_changed": ("D", 2, "content"), "main_image_changed": ("D", 2, "content"),
}
LEVEL_RANK = {"S": 5, "A": 4, "B": 3, "C": 2, "D": 1}
DOMAIN_MULTIPLIERS = (1, .4, .2)
COMPETITOR_MULTIPLIERS = (1, .5, .25)


class Reason(BaseModel):
    reason_type: str
    display_text: str
    competitor_count: int
    sku_count: int | None = None
    direction: str | None = None
    event_level: str
    current_state_safe: bool


class OwnProduct(BaseModel):
    id: int
    offer_id: str
    title: str | None
    shop_name: str | None
    main_image_url: str | None


class AttentionGroup(BaseModel):
    group_id: int
    group_name: str
    own_product: OwnProduct
    attention_level: str
    changed_competitor_count: int
    reasons: list[Reason]
    latest_change_at: datetime


class AttentionKpis(BaseModel):
    monitored_product_groups: int
    changed_product_groups_today: int
    changed_competitors_today: int


class GroupAttentionResponse(BaseModel):
    date: date
    kpis: AttentionKpis
    groups: list[AttentionGroup]


def _rate(event: ChangeEvent) -> float | None:
    if event.delta_rate is None:
        return None
    try:
        return abs(float(event.delta_rate))
    except (ValueError, TypeError):
        return None


def _snapshot_coverage(events: list[ChangeEvent], sku_by_snapshot: dict[int, set[str]]) -> float:
    changed_by_snapshot: dict[int, set[str]] = defaultdict(set)
    for event in events:
        if event.snapshot_id is not None and event.entity_key:
            changed_by_snapshot[event.snapshot_id].add(event.entity_key)
    return max((len(skus) / len(sku_by_snapshot[snapshot_id])
                for snapshot_id, skus in changed_by_snapshot.items()
                if sku_by_snapshot.get(snapshot_id)), default=0)


def _sku_sets(
    db: Session, events: list[ChangeEvent]
) -> tuple[dict[int, set[str]], dict[int, set[str]]]:
    snapshot_ids = {event.snapshot_id for event in events if event.snapshot_id is not None}
    snapshots = list(db.scalars(select(ProductSnapshot).where(ProductSnapshot.id.in_(snapshot_ids))).all()) if snapshot_ids else []
    by_snapshot: dict[int, set[str]] = defaultdict(set)
    before_by_snapshot: dict[int, set[str]] = defaultdict(set)
    if snapshots:
        competitor_ids = {snapshot.competitor_id for snapshot in snapshots}
        prior_candidates = list(db.scalars(
            select(ProductSnapshot)
            .where(ProductSnapshot.competitor_id.in_(competitor_ids))
            .order_by(ProductSnapshot.competitor_id, ProductSnapshot.captured_at, ProductSnapshot.id)
        ).all())
        prior_by_current: dict[int, int] = {}
        prior_by_competitor: dict[int, list[ProductSnapshot]] = defaultdict(list)
        prior_keys: dict[int, list[tuple[datetime, int]]] = defaultdict(list)
        for previous in prior_candidates:
            prior_by_competitor[previous.competitor_id].append(previous)
            prior_keys[previous.competitor_id].append((previous.captured_at, previous.id))
        for current in snapshots:
            key = (current.captured_at, current.id)
            candidates = prior_by_competitor[current.competitor_id]
            previous_index = bisect_left(prior_keys[current.competitor_id], key) - 1
            if previous_index >= 0:
                prior_by_current[current.id] = candidates[previous_index].id
        current_by_prior = {previous_id: current_id for current_id, previous_id in prior_by_current.items()}
        snapshot_ids |= set(prior_by_current.values())
        rows = db.execute(
            select(ProductSnapshot.id, SkuSnapshot.sku_id)
            .join(SkuSnapshot, SkuSnapshot.product_snapshot_id == ProductSnapshot.id)
            .where(ProductSnapshot.id.in_(snapshot_ids))
        ).all()
        current_ids = {snapshot.id for snapshot in snapshots}
        for snapshot_id, sku_id in rows:
            if snapshot_id in current_ids:
                by_snapshot[snapshot_id].add(sku_id)
            elif snapshot_id in current_by_prior:
                before_by_snapshot[current_by_prior[snapshot_id]].add(sku_id)
    return by_snapshot, before_by_snapshot


def _reason_rows(events: list[ChangeEvent]) -> list[dict[str, object]]:
    by_type: dict[str, list[ChangeEvent]] = defaultdict(list)
    for event in events:
        by_type[event.change_type].append(event)
    facts: dict[str, dict[str, object]] = {}

    def add(key: str, text: str, level: str, *, sku_count: int | None = None,
            direction: str | None = None, safe: bool = True, priority: int = 99) -> None:
        facts[key] = {"reason_type": key, "display_text": text, "competitor_count": 0,
                      "sku_count": sku_count, "direction": direction, "event_level": level,
                      "current_state_safe": safe, "priority": priority, "competitors": set()}

    groups = {"price_decrease": ("price_decrease", "竞品降价", "S", 0),
              "price_increase": ("price_increase", "竞品涨价", "B", 4),
              "sku_sold_out": ("sku_sold_out", "SKU 售罄", "A", 2),
              "sku_restocked": ("sku_restocked", "SKU 恢复有货", "A", 5),
              "sku_removed": ("sku_removed", "减少 SKU", "A", 3),
              "sku_added": ("sku_added", "新增 SKU", "B", 6),
              "stock_changed": ("stock_changed", "出现库存变化", "B", 7),
              "min_order_quantity_decrease": ("min_order_quantity_decrease", "降低起批量", "C", 8),
              "min_order_quantity_increase": ("min_order_quantity_increase", "提高起批量", "C", 8)}
    for change_type, (key, label, level, priority) in groups.items():
        if key == "stock_changed":
            continue
        if by_type[change_type]:
            add(key, label, level, direction=change_type, priority=priority)
    if any(by_type[kind] for kind in ("stock_increase", "stock_decrease", "stock_changed")):
        add("stock_changed", "出现库存变化", "B", priority=7)
    if by_type["title_changed"] or by_type["main_image_changed"]:
        add("product_content_changed", "调整商品内容", "D", priority=9)
    if by_type["product_offline"] and not by_type["product_online"]:
        add("product_offline", "商品下架", "A", direction="offline", priority=1)
    elif by_type["product_online"] and not by_type["product_offline"]:
        add("product_online", "商品恢复上架", "B", direction="online", priority=6)

    by_competitor: dict[int, list[ChangeEvent]] = defaultdict(list)
    for event in events:
        by_competitor[event.competitor_id].append(event)
    for competitor_id, comp_events in by_competitor.items():
        prices: dict[str | None, list[ChangeEvent]] = defaultdict(list)
        supplies: dict[str, list[ChangeEvent]] = defaultdict(list)
        for event in comp_events:
            if event.change_type in {"price_decrease", "price_increase"}:
                prices[event.entity_key].append(event)
            if event.change_type in {"sku_sold_out", "sku_restocked"} and event.entity_key:
                supplies[event.entity_key].append(event)
        reversed_price = any({e.change_type for e in es} == {"price_decrease", "price_increase"} for es in prices.values())
        reversed_price_entities = {
            entity for entity, entity_events in prices.items()
            if {event.change_type for event in entity_events} == {"price_decrease", "price_increase"}
        }
        reversed_supply = any({e.change_type for e in es} == {"sku_sold_out", "sku_restocked"} for es in supplies.values())
        reversed_supply_skus = {
            entity for entity, entity_events in supplies.items()
            if {event.change_type for event in entity_events} == {"sku_sold_out", "sku_restocked"}
        }
        lifecycle = [e for e in comp_events if e.change_type in {"product_offline", "product_online"}]
        reversed_lifecycle = len({e.change_type for e in lifecycle}) > 1
        for key in ("price_decrease", "price_increase"):
            if key in facts and any(e.change_type == key and e.entity_key not in reversed_price_entities for e in comp_events):
                facts[key]["competitors"].add(competitor_id)
        if reversed_price:
            if "price_adjusted_multiple_times" not in facts:
                add("price_adjusted_multiple_times", "今日多次调整价格", "S", safe=True, priority=0)
            facts["price_adjusted_multiple_times"]["competitors"].add(competitor_id)
        if reversed_supply:
            if "sku_supply_changed" not in facts:
                add("sku_supply_changed", "今日发生 SKU 供应状态变化", "A", safe=True, priority=2)
            facts["sku_supply_changed"]["competitors"].add(competitor_id)
        if reversed_lifecycle:
            if "lifecycle_changed" not in facts:
                add("lifecycle_changed", "今日发生上下架状态变化", "A", safe=True, priority=1)
            facts["lifecycle_changed"]["competitors"].add(competitor_id)
        for key in facts:
            if key == "stock_changed":
                matching = [event for event in comp_events if event.change_type in {"stock_increase", "stock_decrease", "stock_changed"}]
                terminal = {(event.entity_key, "stock_decrease" if event.change_type == "sku_sold_out" else "stock_increase")
                            for event in comp_events if event.change_type in {"sku_sold_out", "sku_restocked"}}
                matching = [event for event in matching if not (
                    event.entity_key and (event.entity_key, event.change_type) in terminal
                )]
                if matching:
                    facts[key]["competitors"].add(competitor_id)
                continue
            if key in by_type and key not in {"price_decrease", "price_increase"}:
                matching = [event for event in comp_events if event.change_type == key]
                if key in {"sku_sold_out", "sku_restocked"}:
                    matching = [event for event in matching if event.entity_key not in reversed_supply_skus]
                if key in {"product_offline", "product_online"} and reversed_lifecycle:
                    matching = []
                if matching:
                    facts[key]["competitors"].add(competitor_id)
            if key == "product_content_changed" and any(e.change_type in {"title_changed", "main_image_changed"} for e in comp_events):
                facts[key]["competitors"].add(competitor_id)
            if key in {"product_offline", "product_online"}:
                if any(e.change_type == key for e in comp_events):
                    facts[key]["competitors"].add(competitor_id)
    reason_events = {
        "price_decrease": {"price_decrease"}, "price_increase": {"price_increase"},
        "price_adjusted_multiple_times": {"price_decrease", "price_increase"},
        "sku_sold_out": {"sku_sold_out"}, "sku_restocked": {"sku_restocked"},
        "sku_supply_changed": {"sku_sold_out", "sku_restocked"},
        "sku_removed": {"sku_removed"}, "sku_added": {"sku_added"},
        "stock_changed": {"stock_increase", "stock_decrease", "stock_changed"},
        "min_order_quantity_decrease": {"min_order_quantity_decrease"},
        "min_order_quantity_increase": {"min_order_quantity_increase"},
        "product_content_changed": {"title_changed", "main_image_changed"},
        "product_offline": {"product_offline"}, "product_online": {"product_online"},
        "lifecycle_changed": {"product_offline", "product_online"},
    }
    result = []
    for fact in facts.values():
        competitors = fact.pop("competitors")
        if not competitors:
            continue
        fact["competitor_count"] = len(competitors)
        matched = [event for event in events if event.change_type in reason_events[fact["reason_type"]]]
        sku_count = len({event.entity_key for event in matched if event.entity_key})
        if sku_count:
            fact["sku_count"] = sku_count
        label = fact["display_text"]
        if fact["reason_type"] == "price_decrease" and sku_count > 1:
            label = "降价（多个 SKU）"
        if fact["reason_type"] == "stock_changed":
            by_sku: dict[str, set[str]] = defaultdict(set)
            for event in matched:
                if event.entity_key and event.change_type in {"stock_increase", "stock_decrease"}:
                    by_sku[event.entity_key].add(event.change_type)
            if any(len(directions) > 1 for directions in by_sku.values()):
                label = "库存多次变化"
                fact["current_state_safe"] = True
                fact["direction"] = None
        fact["display_text"] = f"{len(competitors)} 家竞品{label}"
        fact.pop("priority")
        result.append(fact)
    return sorted(result, key=lambda item: (next((p for k, _, _, p in groups.values() if k == item["reason_type"]),
                                               {"lifecycle_changed": 1, "price_adjusted_multiple_times": 0, "sku_supply_changed": 2,
                                                "product_offline": 1, "product_online": 6, "product_content_changed": 9}.get(item["reason_type"], 99)),
                                             -int(item["competitor_count"])))[:3]


def _group_score(events_by_competitor: dict[int, list[ChangeEvent]], sku_by_snapshot: dict[int, set[str]],
                 sku_before_snapshot: dict[int, set[str]]) -> tuple[float, str, str, int]:
    contributions = []
    all_events = [event for events in events_by_competitor.values() for event in events]
    for competitor_id, events in events_by_competitor.items():
        domains: dict[str, list[ChangeEvent]] = defaultdict(list)
        for event in events:
            if event.change_type in EVENTS:
                domains[EVENTS[event.change_type][2]].append(event)
        domain_values = []
        for domain, domain_events in domains.items():
            base = max(EVENTS[event.change_type][1] for event in domain_events)
            types = {event.change_type for event in domain_events}
            if domain == "price":
                decreases = [event for event in domain_events if event.change_type == "price_decrease"]
                rate = max((_rate(event) or 0 for event in decreases), default=0)
                base += 8 if rate >= 5 else 4 if rate >= 1 else 0
                sku_ids = {event.entity_key for event in decreases if event.entity_key}
                if len(sku_ids) > 1:
                    base += 2
                    coverage = _snapshot_coverage(decreases, sku_by_snapshot)
                    base += (2 if coverage >= .3 else 0) + (2 if coverage >= .6 else 0)
                base = min(base, 54)
            elif domain == "stock" and types <= {"stock_increase", "stock_decrease", "stock_changed"}:
                sku_ids = {event.entity_key for event in domain_events if event.entity_key}
                coverage = _snapshot_coverage(domain_events, sku_by_snapshot)
                base += int(len(sku_ids) > 1) + int(coverage >= .3) + int(coverage >= .6)
                base = min(15, base)
            elif domain == "sku":
                sku_ids = {event.entity_key for event in domain_events if event.entity_key}
                removals = [event for event in domain_events if event.change_type == "sku_removed"]
                additions = [event for event in domain_events if event.change_type == "sku_added"]
                if removals:
                    sku_ids = {event.entity_key for event in removals if event.entity_key}
                if additions and not removals:
                    sku_ids = {event.entity_key for event in additions if event.entity_key}
                base += min(6, len(sku_ids) * 2)
                base = min(base, max(EVENTS[e.change_type][1] for e in domain_events) * 1.25)
            domain_values.append(base)
        domain_values.sort(reverse=True)
        score = sum(value * DOMAIN_MULTIPLIERS[i] for i, value in enumerate(domain_values[:3]))
        contributions.append((score, competitor_id))
    contributions.sort(key=lambda row: (-row[0], row[1]))
    score = sum(value * COMPETITOR_MULTIPLIERS[i] for i, (value, _) in enumerate(contributions[:3]))
    n = len(contributions)
    score += {1: 0, 2: 3, 3: 6, 4: 8}.get(n, 10)
    action_competitors: dict[str, set[int]] = defaultdict(set)
    for event in all_events:
        if EVENTS[event.change_type][0] in {"S", "A"}:
            action_competitors[event.change_type].add(event.competitor_id)
    score += 8 if any(len(ids) >= 3 for ids in action_competitors.values()) else (
        4 if any(len(ids) >= 2 for ids in action_competitors.values()) else 0
    )
    domains = {EVENTS[event.change_type][2] for event in all_events if event.change_type in EVENTS}
    score += 0 if len(domains) < 2 else 2 if len(domains) == 2 else 4
    strongest = max((LEVEL_RANK[EVENTS[event.change_type][0]] for event in all_events if event.change_type in EVENTS), default=0)
    event_level = next((level for level, rank in LEVEL_RANK.items() if rank == strongest), "D")
    strong = 0
    for event in all_events:
        if event.change_type == "price_decrease" and _rate(event) is not None and _rate(event) >= 5 and event.entity_key is None:
            strong = max(strong, 2)
    for competitor_id, events in events_by_competitor.items():
        sku_price = {event.entity_key for event in events if event.change_type == "price_decrease" and event.entity_key and _rate(event) is not None and _rate(event) >= 5}
        sold = {event.entity_key for event in events if event.change_type == "sku_sold_out" and event.entity_key}
        removed = {event.entity_key for event in events if event.change_type == "sku_removed" and event.entity_key}
        remove_snapshots = {event.snapshot_id for event in events if event.change_type == "sku_removed" and event.snapshot_id is not None}
        denom = max((len(sku_before_snapshot.get(snapshot_id, ())) for snapshot_id in remove_snapshots), default=0)
        if len(sku_price) >= 2:
            strong = max(strong, 2)
        if len(sold) >= 2:
            strong = max(strong, 1)
        if denom and len(removed) / denom >= .3:
            strong = max(strong, 1)
    decrease_groups = {e.competitor_id for e in all_events if e.change_type == "price_decrease"}
    offline_groups = {e.competitor_id for e in all_events if e.change_type == "product_offline"}
    sold_groups = {e.competitor_id for e in all_events if e.change_type == "sku_sold_out"}
    if len(decrease_groups) >= 3 or len(offline_groups) >= 2:
        strong = 2
    elif len(decrease_groups) >= 2 or len(offline_groups) >= 1 or len(sold_groups) >= 2:
        strong = max(strong, 1)
    level = 2 if score >= 60 else 1 if score >= 30 else 0
    level = max(level, strong)
    types = {event.change_type for event in all_events}
    if types and types <= {"min_order_quantity_decrease", "min_order_quantity_increase", "title_changed", "main_image_changed"}:
        level = min(level, 0)
    if types and types <= {"stock_increase", "stock_decrease", "stock_changed"}:
        level = min(level, 1)
    return score, ("重点关注", "建议查看", "一般变化")[2-level], event_level, strongest


@router.get("/group-attention", response_model=GroupAttentionResponse)
def get_group_attention(db: Session = Depends(get_db)) -> GroupAttentionResponse:
    business_date, start_utc, end_utc = business_day_bounds()
    end_utc = min(end_utc, datetime.now(timezone.utc).replace(tzinfo=None))
    groups = list(db.scalars(select(CompetitorGroup).order_by(CompetitorGroup.id)).all())
    group_ids = [group.id for group in groups]
    members = list(db.scalars(select(Competitor).where(Competitor.group_id.in_(group_ids))).all()) if group_ids else []
    by_group: dict[int, list[Competitor]] = defaultdict(list)
    for member in members:
        by_group[member.group_id].append(member)
    eligible = {group.id for group in groups if any(m.group_role == "own" for m in by_group[group.id])
                and any(m.group_role == "competitor" for m in by_group[group.id])}
    monitored_count = len(eligible)
    competitor_ids = {m.id for group_id in eligible for m in by_group[group_id] if m.group_role == "competitor"}
    rows = list(db.scalars(select(ChangeEvent).where(
        ChangeEvent.competitor_id.in_(competitor_ids), ChangeEvent.detected_at >= start_utc,
        ChangeEvent.detected_at < end_utc,
    ).order_by(ChangeEvent.detected_at, ChangeEvent.id)).all()) if competitor_ids else []
    rows = [event for event in rows if event.change_type in EVENTS]
    snapshots, sku_before = _sku_sets(db, rows)
    events_by_group: dict[int, dict[int, list[ChangeEvent]]] = defaultdict(lambda: defaultdict(list))
    competitor_to_group = {m.id: m.group_id for m in members if m.group_role == "competitor" and m.group_id in eligible}
    for event in rows:
        group_id = competitor_to_group.get(event.competitor_id)
        if group_id is not None:
            events_by_group[group_id][event.competitor_id].append(event)
    output = []
    changed_competitors = set()
    for group in groups:
        if group.id not in eligible or not events_by_group[group.id]:
            continue
        own = next(m for m in by_group[group.id] if m.group_role == "own")
        comp_events = events_by_group[group.id]
        group_events = [event for comp in comp_events.values() for event in comp]
        changed_competitors.update(comp_events)
        score, level, _strongest_text, strongest = _group_score(comp_events, snapshots, sku_before)
        reasons = _reason_rows(group_events)
        output.append({
            "group_id": group.id, "group_name": group.name,
            "own_product": {"id": own.id, "offer_id": own.offer_id, "title": own.title,
                            "shop_name": own.shop_name, "main_image_url": own.main_image_url},
            "attention_level": level, "changed_competitor_count": len(comp_events),
            "reasons": reasons, "latest_change_at": max(event.detected_at for event in group_events),
            "_score": score, "_strongest": strongest,
        })
    level_order = {"重点关注": 2, "建议查看": 1, "一般变化": 0}
    output.sort(key=lambda item: (-level_order[item["attention_level"]], -item["_score"],
                                  -item["_strongest"], -item["changed_competitor_count"],
                                  -item["latest_change_at"].timestamp(), item["group_id"]))
    for item in output:
        item.pop("_score")
        item.pop("_strongest")
    return GroupAttentionResponse(date=business_date, kpis=AttentionKpis(
        monitored_product_groups=monitored_count, changed_product_groups_today=len(output),
        changed_competitors_today=len(changed_competitors)), groups=output)
