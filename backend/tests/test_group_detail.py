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
from app.models import Base, ChangeEvent, CollectionRun, Competitor, CompetitorGroup, OperatingMetricObservation, ProductSnapshot, SkuSnapshot


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
    test_client = TestClient(app)
    try:
        yield test_client, session_factory
    finally:
        test_client.close()
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


def test_operating_metrics_coverage_counts_active_offers_including_own_and_offline(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    with client[1]() as session:
        group = add_group(session)
        own = add_member(session, group.id, "101", role="own", active=True)
        offline = add_member(session, group.id, "102", active=True, status="offline")
        stopped = add_member(session, group.id, "103", active=False)
        run = CollectionRun(
            competitor_id=offline.id,
            started_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
            finished_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
            status="success",
            operating_metrics_status="success",
        )
        session.add(run)
        session.flush()
        session.add(OperatingMetricObservation(
            competitor_id=offline.id, collection_run_id=run.id, platform="1688", offer_id=offline.offer_id,
            metric_key="monthly_deal", status="observed", raw_value="20+",
            source="1688_official_procurement_assistant_top", observed_at=run.started_at,
        ))
        session.commit()

    body = client[0].get(f"/api/competitor-groups/{group.id}/detail").json()
    assert body["operating_metrics_coverage"]["monthly_deal"] == {"has_history_valid_values": 1, "active_offers": 2}
    offline_facts = next(item for item in body["competitors"] if item["id"] == offline.id)
    metric = next(item for item in offline_facts["operating_metrics"] if item["metric_key"] == "monthly_deal")
    assert metric["latest_valid"]["raw_value"] == "20+"
    assert own.id == body["own_product"]["id"]
    assert next(member for member in body["competitors"] if member["id"] == stopped.id)["is_active"] is False


def test_operating_metrics_queries_are_bounded_for_many_group_members(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    with client[1]() as session:
        group = add_group(session)
        members = [add_member(session, group.id, str(200 + index)) for index in range(30)]
        session.commit()

    engine = client[1].kw["bind"]
    metric_queries: list[str] = []

    def count_metric_queries(_connection, _cursor, statement, _parameters, _context, _executemany):
        if "operating_metric_observations" in statement.lower():
            metric_queries.append(statement)

    event.listen(engine, "before_cursor_execute", count_metric_queries)
    try:
        response = client[0].get(f"/api/competitor-groups/{group.id}/detail")
    finally:
        event.remove(engine, "before_cursor_execute", count_metric_queries)

    assert response.status_code == 200
    assert len(response.json()["competitors"]) == len(members)
    assert len(metric_queries) == 2


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


def test_positions_competition_ties_numeric_price_and_r2(client):
    with client[1]() as session:
        group = add_group(session)
        offers = [add_member(session, group.id, str(i), role="own" if i == 2 else "competitor") for i in range(9)]
        for i, offer in enumerate(offers):
            add_snapshot(session, offer, datetime.now(timezone.utc)-timedelta(days=20+i), moq=1 if i < 2 else 2, price_min=Decimal("9") if i < 3 else Decimal("100"), price_max=Decimal("150"), skus=[("a", "规格", 0)])
        session.commit()
    body = client[0].get(f"/api/competitor-groups/{group.id}/detail").json()
    moq = body["position"]["min_order_quantity"]
    assert moq["eligible_count"] == 9
    assert moq["offers"][str(offers[2].id)]["rank_asc"] == 3
    assert moq["offers"][str(offers[2].id)]["rank_desc"] == 1
    assert moq["offers"][str(offers[0].id)]["rank_desc"] == 8
    price = body["position"]["display_price_min"]
    assert price["offers"][str(offers[0].id)]["rank_asc"] == 1
    assert price["offers"][str(offers[3].id)]["rank_asc"] == 4
    assert price["offers"][str(offers[0].id)]["rank_desc"] == 7
    assert body["position"]["total_stock"]["eligible_count"] == 9


@pytest.mark.parametrize("active,status_,snapshot,moq,low,high,reason", [
    (False, "active", True, 1, "9", "10", "not_monitored"),
    (True, "offline", True, 1, "9", "10", "offline"),
    (True, "unknown", True, 1, "9", "10", "status_unknown"),
    (True, "active", False, 1, "9", "10", "no_snapshot"),
    (True, "active", True, 1, "9", None, "unknown_value"),
    (True, "active", True, None, "10", "9", "unknown_value"),
    (True, "active", True, 2, "0", "0", None),
])
def test_position_exclusion_and_valid_zero(client, active, status_, snapshot, moq, low, high, reason):
    with client[1]() as session:
        group = add_group(session)
        member = add_member(session, group.id, "1", active=active, status=status_)
        if snapshot:
            add_snapshot(session, member, datetime.now(timezone.utc), moq=moq, price_min=Decimal(low), price_max=Decimal(high) if high else None)
        session.commit()
    body = client[0].get(f"/api/competitor-groups/{group.id}/detail").json()
    value = body["position"]["display_price_min"]["offers"][str(member.id)]
    assert value["reason"] == reason
    assert value["eligible"] == (reason is None)
    assert value["rank_asc"] == (1 if reason is None else None)
    if snapshot and active and status_ == "active":
        assert body["position"]["sku_count"]["eligible_count"] == 1
        assert body["position"]["total_stock"]["eligible_count"] == 0


def test_event_paging_fixed_upper_bound_full_counts_and_context(client):
    with client[1]() as session:
        group = add_group(session)
        own = add_member(session, group.id, "own", role="own")
        other = add_member(session, group.id, "other", active=False, status="offline")
        stamp = datetime.now(timezone.utc)
        snapshots = {m.id: add_snapshot(session, m, stamp) for m in [own, other]}
        ids = []
        for i in range(45):
            event = add_event(session, other if i != 0 else own, snapshots[(other if i != 0 else own).id], "price_decrease" if i == 0 else "stock_decrease", stamp, old_value="10", new_value="9")
            ids.append(event.id)
        session.commit()
    body = client[0].get(f"/api/competitor-groups/{group.id}/detail").json()
    assert len(body["today"]["events"]) == 20
    assert body["today"]["competitor_event_count"] == 44
    assert body["today"]["event_pagination"]["has_more"] is True
    assert body["event_page"]["important_offer_ids"] == [own.id]
    assert len(body["event_page"]["items"]) == 1
    url = f"/api/competitor-groups/{group.id}/events"
    params = {"range": "7", "mode": "all", "limit": 7}
    first = client[0].get(url, params=params).json()
    with client[1]() as session:
        add_event(session, other, snapshots[other.id], "price_increase", stamp)
        session.commit()
    pages, current = [], first
    while True:
        pages.extend(current["items"])
        assert current["important_offer_ids"] == [own.id]
        if not current["has_more"]:
            assert current["next_cursor"] is None
            break
        current = client[0].get(url, params={**params, "cursor": current["next_cursor"]}).json()
    assert [e["id"] for e in pages] == list(reversed(ids))
    assert all(e["old_value"] == "10" and e["new_value"] == "9" for e in pages)
    assert client[0].get(url, params={**params, "limit": 8, "cursor": first["next_cursor"]}).status_code == 422
    with client[1]() as session:
        session.get(Competitor, other.id).group_id = None
        session.commit()
    assert client[0].get(url, params={**params, "cursor": first["next_cursor"]}).status_code == 409


@pytest.mark.parametrize("params", [{"range": "3"}, {"mode": "bad"}, {"limit": 0}, {"limit": 101}, {"cursor": "garbage"}, {"cursor": "e30="}])
def test_event_invalid_parameters(client, params):
    with client[1]() as session:
        group = add_group(session)
        session.commit()
    assert client[0].get(f"/api/competitor-groups/{group.id}/events", params=params).status_code == 422


@pytest.mark.parametrize("range_", ["today", "7", "30"])
def test_event_boundaries_precision_and_midnight_context(client, monkeypatch, range_):
    import app.group_detail as module
    today = date(2026, 10, 9)
    start, end = business_date_utc_bounds(today)
    monkeypatch.setattr(module, "business_day_bounds", lambda: (today, start, end))
    with client[1]() as session:
        group = add_group(session)
        member = add_member(session, group.id, "1")
        snap = add_snapshot(session, member, start)
        expected = []
        for delta in [1, 2, 3]:
            expected.append(add_event(session, member, snap, "sku_added", start+timedelta(microseconds=delta)).id)
        add_event(session, member, snap, "sku_added", end)
        session.commit()
    url = f"/api/competitor-groups/{group.id}/events"
    params = {"range": range_, "limit": 1}
    first = client[0].get(url, params=params).json()
    monkeypatch.setattr(module, "business_day_bounds", lambda: (today+timedelta(days=1), end, end+timedelta(days=1)))
    ids, current = [], first
    while True:
        ids.extend(e["id"] for e in current["items"])
        assert current["window_end"] == first["window_end"]
        if not current["has_more"]:
            break
        current = client[0].get(url, params={**params, "cursor": current["next_cursor"]}).json()
    assert ids == list(reversed(expected))
    assert len(client[0].get(url, params={**params, "limit": 100}).json()["items"]) >= 1


def test_empty_event_metadata_and_missing_group(client):
    with client[1]() as session:
        group = add_group(session)
        session.commit()
    body = client[0].get(f"/api/competitor-groups/{group.id}/events").json()
    assert body["items"] == body["important_offer_ids"] == []
    assert body["through_event_id"] == 0 and body["next_cursor"] is None and not body["has_more"]
    assert client[0].get("/api/competitor-groups/999/events").status_code == 404


def test_malformed_cursor_numeric_and_member_structure(client):
    import base64, json
    with client[1]() as session:
        group = add_group(session)
        member = add_member(session, group.id, "1")
        stamp = datetime.now(timezone.utc)
        snap = add_snapshot(session, member, stamp)
        for _ in range(2):
            add_event(session, member, snap, "sku_added", stamp)
        session.commit()
    url = f"/api/competitor-groups/{group.id}/events"
    first = client[0].get(url, params={"limit": 1}).json()
    original = json.loads(base64.urlsafe_b64decode(first["next_cursor"]))
    for mutation in [{"through": 2**64}, {"last_id": True}, {"group": True}, {"members": [42]}, {"start": "invalid"}]:
        cursor = base64.urlsafe_b64encode(json.dumps({**original, **mutation}).encode()).decode()
        assert client[0].get(url, params={"limit": 1, "cursor": cursor}).status_code == 422


@pytest.mark.parametrize("invalid_name", ["&nbsp;", "&#160; \t", " \n\t ", ""])
def test_invalid_recent_sku_name_falls_back_consistently(client, invalid_name):
    with client[1]() as session:
        group = add_group(session)
        member = add_member(session, group.id, "sku-history")
        stamp = datetime.now(timezone.utc)
        add_snapshot(session, member, stamp - timedelta(days=2), skus=[("sku-1", "旧名称", 10)])
        add_snapshot(session, member, stamp - timedelta(days=1), skus=[("sku-1", "  红色&nbsp; &gt;\t A19  ", 10)])
        latest = add_snapshot(session, member, stamp, skus=[("sku-1", invalid_name, 9)])
        change = add_event(session, member, latest, "price_decrease", stamp, entity_key="sku-1", old_value="10", new_value="9")
        session.commit()
    response = client[0].get(f"/api/competitor-groups/{group.id}/detail")
    assert response.status_code == 200
    body = response.json()
    single = client[0].get(f"/api/competitors/{member.id}/detail").json()
    events = client[0].get(f"/api/competitor-groups/{group.id}/events").json()
    results = [body["competitors"][0]["latest_change"], body["event_page"]["items"][0], body["today"]["events"][0], events["items"][0], single["recent_changes"][0], single["latest_price_change"]]
    assert all(item["id"] == change.id and item["sku_name"] == "红色 > A19" for item in results)
