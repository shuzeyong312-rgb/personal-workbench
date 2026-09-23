from collections.abc import Generator
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import app
from app.dashboard import business_date_utc_bounds, business_day_bounds
from app.models import Base, ChangeEvent, Competitor, CompetitorGroup, ProductSnapshot, SkuSnapshot


@pytest.fixture()
def client() -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client, session_factory
    app.dependency_overrides.clear()
    engine.dispose()


def test_missing_group_returns_stable_error(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    response = client[0].get("/api/competitor-groups/999/detail")

    assert response.status_code == 404
    assert response.json() == {"code": "competitor_group_not_found", "message": "竞品组不存在"}


def test_unbound_group_returns_empty_real_facts_and_default_range(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    with client[1]() as session:
        group = CompetitorGroup(name="A19", created_at=datetime.now(timezone.utc))
        session.add(group)
        session.commit()

    response = client[0].get(f"/api/competitor-groups/{group.id}/detail")

    assert response.status_code == 200
    body = response.json()
    assert body["range_days"] == 7
    assert body["group"]["id"] == group.id
    assert body["group"]["name"] == "A19"
    assert body["own_product"] is None
    assert body["competitors"] == []
    assert body["summary"]["direct_competitor_count"] == 0
    assert body["summary"]["price_lower_than_own"] == {
        "matched_count": 0,
        "comparable_count": 0,
    }
    assert body["today"]["events"] == []
    assert body["action_window"]["days"] == 7


@pytest.mark.parametrize("days", [0, 8, 14, 31])
def test_invalid_range_days_returns_422(
    client: tuple[TestClient, sessionmaker[Session]], days: int
) -> None:
    with client[1]() as session:
        group = CompetitorGroup(name="A19", created_at=datetime.now(timezone.utc))
        session.add(group)
        session.commit()

    response = client[0].get(f"/api/competitor-groups/{group.id}/detail?days={days}")

    assert response.status_code == 422


def add_group(session: Session, name: str = "A19") -> CompetitorGroup:
    group = CompetitorGroup(name=name, created_at=datetime.now(timezone.utc))
    session.add(group)
    session.flush()
    return group


def add_member(
    session: Session,
    group_id: int,
    offer_id: str,
    *,
    role: str = "competitor",
    active: bool = True,
    status: str = "active",
    title: str | None = None,
) -> Competitor:
    now = datetime.now(timezone.utc)
    member = Competitor(
        group_id=group_id,
        group_role=role,
        platform="1688",
        offer_id=offer_id,
        url=f"https://detail.1688.com/offer/{offer_id}.html",
        title=title or f"商品 {offer_id}",
        shop_name="真实店铺",
        main_image_url="https://example.com/item.jpg",
        status=status,
        is_active=active,
        created_at=now,
        updated_at=now,
        last_collected_at=now,
    )
    session.add(member)
    session.flush()
    return member


def add_snapshot(
    session: Session,
    member: Competitor,
    captured_at: datetime,
    *,
    price_min: Decimal | None = Decimal("40"),
    price_max: Decimal | None = Decimal("45"),
    moq: int | None = 1,
    skus: list[tuple[str, str, int | None]] | None = None,
) -> ProductSnapshot:
    snapshot = ProductSnapshot(
        competitor_id=member.id,
        captured_at=captured_at,
        title=member.title or member.offer_id,
        shop_name=member.shop_name or "店铺",
        price_min=price_min,
        price_max=price_max,
        min_order_quantity=moq,
        product_status=member.status,
        collection_source="html",
    )
    if skus is not None:
        snapshot.skus = [
            SkuSnapshot(sku_id=sku_id, sku_name=name, stock=stock, price=None)
            for sku_id, name, stock in skus
        ]
    session.add(snapshot)
    session.flush()
    return snapshot


def add_event(
    session: Session,
    member: Competitor,
    snapshot: ProductSnapshot | None,
    change_type: str,
    detected_at: datetime,
    *,
    entity_key: str | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
) -> ChangeEvent:
    change = ChangeEvent(
        competitor_id=member.id,
        snapshot_id=snapshot.id if snapshot is not None else None,
        change_type=change_type,
        entity_key=entity_key,
        old_value=old_value,
        new_value=new_value,
        detected_at=detected_at,
    )
    session.add(change)
    session.flush()
    return change


def utc_at(business_date: date, *, hour: int = 12) -> datetime:
    start, _ = business_date_utc_bounds(business_date)
    return start + timedelta(hours=hour)


def test_bound_facts_comparisons_and_counts_exclude_own_and_other_groups(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    with client[1]() as session:
        group = add_group(session)
        other_group = add_group(session, "B20")
        own = add_member(session, group.id, "100", role="own", active=False, title=None)
        direct = add_member(session, group.id, "200", active=False, status="offline")
        add_member(session, other_group.id, "300")
        timestamp = utc_at(business_day_bounds()[0])
        own_snapshot = add_snapshot(
            session,
            own,
            timestamp,
            price_min=Decimal("50"),
            price_max=Decimal("60"),
            moq=10,
            skus=[("a", "A", 0), ("b", "B", 0)],
        )
        direct_snapshot = add_snapshot(
            session,
            direct,
            timestamp,
            price_min=Decimal("40"),
            price_max=Decimal("45"),
            moq=5,
            skus=[("a", "A", 8)],
        )
        add_event(session, own, own_snapshot, "price_decrease", timestamp)
        add_event(session, direct, direct_snapshot, "stock_increase", timestamp, entity_key="a")
        session.commit()

    body = client[0].get(f"/api/competitor-groups/{group.id}/detail").json()

    assert body["own_product"]["id"] == own.id
    assert body["own_product"]["role"] == "own"
    assert body["own_product"]["latest_snapshot"]["sku_count"] == 2
    assert body["own_product"]["latest_snapshot"]["total_stock"] == 0
    assert body["competitors"][0]["id"] == direct.id
    assert body["competitors"][0]["status"] == "offline"
    assert body["competitors"][0]["is_active"] is False
    assert body["competitors"][0]["latest_snapshot"]["total_stock"] == 8
    assert body["competitors"][0]["comparison"] == {
        "price": "lower",
        "min_order_quantity": "lower",
        "sku_count": "fewer",
        "total_stock": "higher",
    }
    assert body["summary"]["direct_competitor_count"] == 1
    assert body["summary"]["monitored_competitor_count"] == 0
    assert body["summary"]["price_lower_than_own"] == {"matched_count": 1, "comparable_count": 1}
    assert body["today"]["own_event_count"] == 1
    assert body["today"]["competitor_event_count"] == 1
    assert body["today"]["changed_competitor_count"] == 1
    assert body["today"]["events"][0]["sku_name"] == "A"


def test_latest_snapshot_and_change_use_id_tiebreak_and_keep_empty_snapshot_truth(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    with client[1]() as session:
        group = add_group(session)
        own = add_member(session, group.id, "101", role="own")
        timestamp = utc_at(business_day_bounds()[0])
        add_snapshot(session, own, timestamp, price_min=Decimal("10"), price_max=Decimal("10"), skus=[])
        latest = add_snapshot(session, own, timestamp, price_min=Decimal("20"), price_max=Decimal("20"), skus=[])
        first_event = add_event(session, own, latest, "title_changed", timestamp)
        second_event = add_event(session, own, latest, "main_image_changed", timestamp)
        session.commit()

    facts = client[0].get(f"/api/competitor-groups/{group.id}/detail").json()["own_product"]

    assert facts["latest_snapshot"]["id"] == latest.id
    assert facts["latest_snapshot"]["price_min"] == "20.00"
    assert facts["latest_snapshot"]["sku_count"] == 0
    assert facts["latest_snapshot"]["total_stock"] is None
    assert facts["latest_change"]["id"] == second_event.id
    assert facts["latest_change"]["id"] > first_event.id


@pytest.mark.parametrize(
    ("own_min", "own_max", "competitor_min", "competitor_max", "expected"),
    [
        ("50", "60", "40", "45", "lower"),
        ("40", "45", "50", "60", "higher"),
        ("40", "50", "50", "60", "overlap"),
        ("20", "30", "100", "120", "higher"),
        ("40", "40", "40", "40", "overlap"),
        (None, "60", "40", "45", "unknown"),
        ("50", "60", "40", None, "unknown"),
    ],
)
def test_price_comparison_requires_complete_ranges(
    client: tuple[TestClient, sessionmaker[Session]],
    own_min: str | None,
    own_max: str | None,
    competitor_min: str | None,
    competitor_max: str | None,
    expected: str,
) -> None:
    with client[1]() as session:
        group = add_group(session)
        own = add_member(session, group.id, "101", role="own")
        direct = add_member(session, group.id, "102")
        timestamp = utc_at(business_day_bounds()[0])
        add_snapshot(
            session,
            own,
            timestamp,
            price_min=Decimal(own_min) if own_min is not None else None,
            price_max=Decimal(own_max) if own_max is not None else None,
            skus=[],
        )
        add_snapshot(
            session,
            direct,
            timestamp,
            price_min=Decimal(competitor_min) if competitor_min is not None else None,
            price_max=Decimal(competitor_max) if competitor_max is not None else None,
            skus=[],
        )
        session.commit()

    comparison = client[0].get(f"/api/competitor-groups/{group.id}/detail").json()["competitors"][0]["comparison"]
    assert comparison["price"] == expected


@pytest.mark.parametrize(
    ("own_moq", "competitor_moq", "expected"),
    [(5, 2, "lower"), (2, 5, "higher"), (5, 5, "equal"), (None, 2, "unknown")],
)
def test_moq_comparison(
    client: tuple[TestClient, sessionmaker[Session]],
    own_moq: int | None,
    competitor_moq: int | None,
    expected: str,
) -> None:
    with client[1]() as session:
        group = add_group(session)
        own = add_member(session, group.id, "101", role="own")
        direct = add_member(session, group.id, "102")
        timestamp = utc_at(business_day_bounds()[0])
        add_snapshot(session, own, timestamp, moq=own_moq, skus=[])
        add_snapshot(session, direct, timestamp, moq=competitor_moq, skus=[])
        session.commit()

    comparison = client[0].get(f"/api/competitor-groups/{group.id}/detail").json()["competitors"][0]["comparison"]
    assert comparison["min_order_quantity"] == expected


def test_incomplete_or_negative_stock_stays_unknown_and_offline_keeps_snapshot(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    with client[1]() as session:
        group = add_group(session)
        own = add_member(session, group.id, "101", role="own")
        direct = add_member(session, group.id, "102", status="offline")
        timestamp = utc_at(business_day_bounds()[0])
        add_snapshot(session, own, timestamp, skus=[("a", "A", 1)])
        add_snapshot(session, direct, timestamp, skus=[("a", "A", -1)])
        session.commit()

    body = client[0].get(f"/api/competitor-groups/{group.id}/detail").json()
    assert body["competitors"][0]["latest_snapshot"]["total_stock"] is None
    assert body["competitors"][0]["comparison"]["total_stock"] == "unknown"
    assert body["competitors"][0]["latest_snapshot"]["captured_at"] == timestamp.isoformat().replace("+00:00", "")


def test_one_unknown_sku_stock_makes_the_complete_total_unknown(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    with client[1]() as session:
        group = add_group(session)
        own = add_member(session, group.id, "101", role="own")
        direct = add_member(session, group.id, "102")
        timestamp = utc_at(business_day_bounds()[0])
        add_snapshot(session, own, timestamp, skus=[("known", "已知库存", 8)])
        add_snapshot(session, direct, timestamp, skus=[("known", "已知库存", 8), ("unknown", "未知库存", None)])
        session.commit()

    body = client[0].get(f"/api/competitor-groups/{group.id}/detail").json()

    assert body["competitors"][0]["latest_snapshot"]["sku_count"] == 2
    assert body["competitors"][0]["latest_snapshot"]["total_stock"] is None
    assert body["competitors"][0]["comparison"]["total_stock"] == "unknown"


@pytest.mark.parametrize(
    ("own_skus", "competitor_skus", "own_stocks", "competitor_stocks", "sku_expected", "stock_expected"),
    [
        (1, 2, [2], [3, 4], "more", "higher"),
        (2, 1, [3, 4], [2], "fewer", "lower"),
        (1, 1, [3], [3], "equal", "equal"),
        (1, 1, [None], [3], "equal", "unknown"),
    ],
)
def test_sku_count_and_complete_stock_comparison_outcomes(
    client: tuple[TestClient, sessionmaker[Session]],
    own_skus: int,
    competitor_skus: int,
    own_stocks: list[int | None],
    competitor_stocks: list[int | None],
    sku_expected: str,
    stock_expected: str,
) -> None:
    with client[1]() as session:
        group = add_group(session)
        own = add_member(session, group.id, "101", role="own")
        direct = add_member(session, group.id, "102")
        timestamp = utc_at(business_day_bounds()[0])
        add_snapshot(session, own, timestamp, skus=[(f"o{i}", f"我方{i}", stock) for i, stock in enumerate(own_stocks[:own_skus])])
        add_snapshot(session, direct, timestamp, skus=[(f"c{i}", f"竞品{i}", stock) for i, stock in enumerate(competitor_stocks[:competitor_skus])])
        session.commit()

    comparison = client[0].get(f"/api/competitor-groups/{group.id}/detail").json()["competitors"][0]["comparison"]
    assert comparison["sku_count"] == sku_expected
    assert comparison["total_stock"] == stock_expected


def test_missing_latest_snapshot_makes_sku_comparison_unknown(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    with client[1]() as session:
        group = add_group(session)
        own = add_member(session, group.id, "101", role="own")
        direct = add_member(session, group.id, "102")
        timestamp = utc_at(business_day_bounds()[0])
        add_snapshot(session, own, timestamp, skus=[])
        session.commit()

    body = client[0].get(f"/api/competitor-groups/{group.id}/detail").json()
    competitor = body["competitors"][0]
    assert competitor["latest_snapshot"] is None
    assert competitor["comparison"]["sku_count"] == "unknown"


def test_today_uses_business_day_boundaries_and_distinct_competitors(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    today, start_utc, end_utc = business_day_bounds()
    with client[1]() as session:
        group = add_group(session)
        own = add_member(session, group.id, "101", role="own")
        first = add_member(session, group.id, "102", active=False)
        second = add_member(session, group.id, "103")
        snapshot = add_snapshot(session, own, start_utc, skus=[])
        first_snapshot = add_snapshot(session, first, start_utc, skus=[])
        second_snapshot = add_snapshot(session, second, start_utc, skus=[])
        add_event(session, own, snapshot, "title_changed", start_utc)
        add_event(session, first, first_snapshot, "price_decrease", start_utc)
        add_event(session, first, first_snapshot, "stock_changed", end_utc - timedelta(seconds=1), entity_key="sku1")
        add_event(session, second, None, "product_offline", end_utc)
        session.commit()

    today_body = client[0].get(f"/api/competitor-groups/{group.id}/detail").json()["today"]

    assert today_body["own_event_count"] == 1
    assert today_body["competitor_event_count"] == 2
    assert today_body["changed_competitor_count"] == 1
    assert [event["role"] for event in today_body["events"]] == ["competitor", "competitor", "own"]
    assert today_body["events"][0]["detected_at"] > today_body["events"][1]["detected_at"]
    assert today_body["events"][1]["detected_at"] == today_body["events"][2]["detected_at"]


def test_action_window_ranges_domains_legacy_and_current_membership(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    today = business_day_bounds()[0]
    with client[1]() as session:
        group = add_group(session)
        own = add_member(session, group.id, "101", role="own")
        active = add_member(session, group.id, "102")
        second = add_member(session, group.id, "103")
        moved = add_member(session, group.id, "104")
        own_snapshot = add_snapshot(session, own, utc_at(today), skus=[])
        active_snapshot = add_snapshot(session, active, utc_at(today), skus=[])
        second_snapshot = add_snapshot(session, second, utc_at(today), skus=[])
        moved_snapshot = add_snapshot(session, moved, utc_at(today), skus=[])
        changes = [
            "price_increase", "price_decrease", "stock_increase", "stock_decrease", "sku_sold_out",
            "sku_restocked", "stock_changed", "sku_added", "sku_removed", "min_order_quantity_increase",
            "min_order_quantity_decrease", "product_offline", "product_online", "title_changed", "main_image_changed",
        ]
        for change_type in changes:
            add_event(
                session,
                active,
                None if change_type == "product_offline" else active_snapshot,
                change_type,
                utc_at(today),
                entity_key="sku1" if change_type in {"stock_increase", "stock_decrease", "sku_sold_out", "sku_restocked", "stock_changed", "sku_added", "sku_removed"} else None,
            )
        add_event(session, own, own_snapshot, "price_decrease", utc_at(today))
        add_event(session, second, second_snapshot, "title_changed", utc_at(today, hour=13))
        add_event(session, moved, moved_snapshot, "stock_increase", utc_at(today))
        moved.group_id = None
        session.commit()

    seven = client[0].get(f"/api/competitor-groups/{group.id}/detail?days=7").json()["action_window"]
    thirty = client[0].get(f"/api/competitor-groups/{group.id}/detail?days=30").json()["action_window"]

    first_day_30 = utc_at(today - timedelta(days=29))
    with client[1]() as session:
        member = session.get(Competitor, active.id)
        assert member is not None
        old_snapshot = add_snapshot(session, member, first_day_30, skus=[])
        add_event(session, member, old_snapshot, "price_decrease", first_day_30)
        session.commit()
    seven = client[0].get(f"/api/competitor-groups/{group.id}/detail?days=7").json()["action_window"]
    thirty = client[0].get(f"/api/competitor-groups/{group.id}/detail?days=30").json()["action_window"]

    assert seven["days"] == 7
    assert thirty["days"] == 30
    assert seven["own_event_count"] == thirty["own_event_count"] == 1
    assert seven["competitor_event_count"] == 16
    assert thirty["competitor_event_count"] == 17
    assert seven["competitors"][0]["competitor_id"] == active.id
    assert seven["competitors"][0]["event_count"] == 15
    assert seven["competitors"][0]["domain_counts"] == {
        "price": 2,
        "stock": 5,
        "sku": 2,
        "min_order_quantity": 2,
        "lifecycle": 2,
        "title": 1,
        "main_image": 1,
    }
    assert moved.id not in [item["competitor_id"] for item in seven["competitors"]]


def test_query_count_does_not_scale_with_group_member_count(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    with client[1]() as session:
        group = add_group(session)
        own = add_member(session, group.id, "101", role="own")
        first = add_member(session, group.id, "102")
        timestamp = utc_at(business_day_bounds()[0])
        own_snapshot = add_snapshot(session, own, timestamp, skus=[])
        first_snapshot = add_snapshot(session, first, timestamp, skus=[("a", "规格 A", 3)])
        add_event(session, first, first_snapshot, "stock_increase", timestamp, entity_key="a")
        session.commit()

    engine = client[1].kw["bind"]
    select_counts: list[int] = []
    current_count = 0

    def count_selects(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        nonlocal current_count
        if statement.lstrip().upper().startswith("SELECT"):
            current_count += 1

    event.listen(engine, "before_cursor_execute", count_selects)
    try:
        client[0].get(f"/api/competitor-groups/{group.id}/detail")
        select_counts.append(current_count)
        with client[1]() as session:
            for number in range(6):
                member = add_member(session, group.id, str(200 + number))
                snapshot = add_snapshot(session, member, timestamp, skus=[("a", "规格 A", 1)])
                add_event(session, member, snapshot, "stock_increase", timestamp, entity_key="a")
            session.commit()
        current_count = 0
        client[0].get(f"/api/competitor-groups/{group.id}/detail")
        select_counts.append(current_count)
    finally:
        event.remove(engine, "before_cursor_execute", count_selects)

    assert select_counts[0] == select_counts[1]
