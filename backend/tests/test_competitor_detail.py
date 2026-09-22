from collections.abc import Generator
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.competitor_detail import calculate_total_stock
from app.dashboard import business_date_utc_bounds, business_day_bounds
from app.database import get_db
from app.main import app
from app.models import Base, ChangeEvent, CollectionRun, Competitor, ProductSnapshot, SkuSnapshot


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


def add_competitor(session: Session, *, active: bool = True) -> Competitor:
    now = datetime.now(timezone.utc)
    competitor = Competitor(
        platform="1688",
        offer_id="123456789",
        url="https://detail.1688.com/offer/123456789.html",
        title="当前商品",
        shop_name="当前店铺",
        main_image_url="https://example.com/product.jpg",
        status="active" if active else "offline",
        is_active=active,
        created_at=now,
        updated_at=now,
    )
    session.add(competitor)
    session.flush()
    return competitor


def utc_for_business_day(business_date: date, *, hours: int = 12) -> datetime:
    start_utc, _ = business_date_utc_bounds(business_date)
    return (start_utc + timedelta(hours=hours)).replace(tzinfo=timezone.utc)


def add_snapshot(
    session: Session,
    competitor_id: int,
    captured_at: datetime,
    *,
    price_min: Decimal | None = Decimal("40.00"),
    price_max: Decimal | None = Decimal("45.00"),
    skus: list[tuple[str, int | None]] | None = None,
) -> ProductSnapshot:
    snapshot = ProductSnapshot(
        competitor_id=competitor_id,
        captured_at=captured_at,
        title="快照商品",
        shop_name="快照店铺",
        price_min=price_min,
        price_max=price_max,
        product_status="unknown",
        collection_source="html",
    )
    if skus is not None:
        snapshot.skus = [
            SkuSnapshot(sku_id=sku_id, sku_name=sku_id, stock=stock, price=None)
            for sku_id, stock in skus
        ]
    session.add(snapshot)
    session.flush()
    return snapshot


def add_change(
    session: Session,
    competitor_id: int,
    snapshot_id: int,
    change_type: str,
    detected_at: datetime,
    *,
    entity_key: str | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
) -> ChangeEvent:
    change = ChangeEvent(
        competitor_id=competitor_id,
        snapshot_id=snapshot_id,
        change_type=change_type,
        entity_key=entity_key,
        old_value=old_value,
        new_value=new_value,
        detected_at=detected_at,
    )
    session.add(change)
    session.flush()
    return change


def test_missing_competitor_returns_stable_detail_error(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    response = client[0].get("/api/competitors/999/detail")

    assert response.status_code == 404
    assert response.json() == {"code": "competitor_not_found", "message": "竞品不存在"}


def test_no_snapshot_returns_continuous_empty_daily_trend(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    with client[1]() as session:
        competitor = add_competitor(session)
        session.commit()

    body = client[0].get(f"/api/competitors/{competitor.id}/detail").json()

    assert body["range_days"] == 7
    assert body["latest_snapshot"] is None
    assert body["latest_skus"] == []
    assert body["latest_price_change"] is None
    assert len(body["daily_trend"]) == 7
    assert [item["date"] for item in body["daily_trend"]] == sorted(item["date"] for item in body["daily_trend"])
    assert all(item["snapshot_id"] is None for item in body["daily_trend"])


def test_daily_trend_returns_continuous_seven_and_thirty_business_days(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    today, _, _ = business_day_bounds()
    with client[1]() as session:
        competitor = add_competitor(session)
        add_snapshot(session, competitor.id, utc_for_business_day(today - timedelta(days=6)))
        add_snapshot(session, competitor.id, utc_for_business_day(today - timedelta(days=2)))
        session.commit()

    seven = client[0].get(f"/api/competitors/{competitor.id}/detail?days=7").json()["daily_trend"]
    thirty = client[0].get(f"/api/competitors/{competitor.id}/detail?days=30").json()["daily_trend"]

    assert len(seven) == 7
    assert len(thirty) == 30
    assert seven[0]["date"] < seven[-1]["date"]
    assert sum(item["snapshot_id"] is not None for item in seven) == 2
    assert seven[1]["snapshot_id"] is None


def test_daily_trend_selects_largest_id_when_snapshot_times_tie(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    today, _, _ = business_day_bounds()
    same_time = utc_for_business_day(today, hours=8)
    with client[1]() as session:
        competitor = add_competitor(session)
        tied_first = add_snapshot(
            session,
            competitor.id,
            same_time,
            price_min=Decimal("35.00"),
            price_max=Decimal("35.00"),
            skus=[("first", 10)],
        )
        tied_last = add_snapshot(
            session,
            competitor.id,
            same_time,
            price_min=Decimal("36.00"),
            price_max=Decimal("36.00"),
            skus=[("last", 20)],
        )
        session.commit()

    body = client[0].get(f"/api/competitors/{competitor.id}/detail").json()
    today_point = body["daily_trend"][-1]

    assert tied_first.id < tied_last.id
    assert today_point["snapshot_id"] == tied_last.id
    assert today_point["price_min"] == "36.00"
    assert today_point["total_stock"] == 20


def test_daily_trend_uses_asia_shanghai_boundary(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    today, _, _ = business_day_bounds()
    start_utc, _ = business_date_utc_bounds(today)
    before_midnight = (start_utc - timedelta(minutes=1)).replace(tzinfo=timezone.utc)
    after_midnight = (start_utc + timedelta(minutes=30)).replace(tzinfo=timezone.utc)
    with client[1]() as session:
        competitor = add_competitor(session)
        previous = add_snapshot(session, competitor.id, before_midnight, price_min=Decimal("39.00"), price_max=Decimal("39.00"))
        current = add_snapshot(session, competitor.id, after_midnight, price_min=Decimal("40.00"), price_max=Decimal("40.00"))
        session.commit()

    trend = client[0].get(f"/api/competitors/{competitor.id}/detail?days=7").json()["daily_trend"]

    assert trend[-1]["date"] == today.isoformat()
    assert trend[-1]["snapshot_id"] == current.id
    assert trend[-2]["snapshot_id"] == previous.id


@pytest.mark.parametrize(
    ("skus", "expected"),
    [
        (["zero", "ten", "twenty"], 30),
        (["zero"], 0),
        (["unknown"], None),
        ([], None),
    ],
)
def test_calculate_total_stock_preserves_zero_null_and_no_sku(
    skus: list[str],
    expected: int | None,
) -> None:
    values = {"zero": 0, "ten": 10, "twenty": 20, "unknown": None}
    sku_rows = [SkuSnapshot(sku_id=sku_id, sku_name=sku_id, stock=values[sku_id]) for sku_id in skus]

    assert calculate_total_stock(sku_rows) == expected


def test_detail_exposes_current_stock_and_daily_stock_with_same_rule(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    today, _, _ = business_day_bounds()
    with client[1]() as session:
        competitor = add_competitor(session)
        snapshot = add_snapshot(
            session,
            competitor.id,
            utc_for_business_day(today),
            skus=[("zero", 0), ("ten", 10), ("twenty", 20)],
        )
        session.commit()

    body = client[0].get(f"/api/competitors/{competitor.id}/detail").json()

    assert body["latest_snapshot"]["total_stock"] == 30
    assert body["daily_trend"][-1]["snapshot_id"] == snapshot.id
    assert body["daily_trend"][-1]["total_stock"] == 30


def test_detail_exposes_product_min_order_quantity_and_sku_price_null_semantics(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    with client[1]() as session:
        competitor = add_competitor(session)
        snapshot = ProductSnapshot(
            competitor_id=competitor.id,
            captured_at=datetime.now(timezone.utc),
            title="商品",
            shop_name="店铺",
            min_order_quantity=1,
            product_status="unknown",
            collection_source="html",
            skus=[
                SkuSnapshot(
                    sku_id="sku-known",
                    sku_name="普通",
                    stock=3,
                    price=Decimal("79.00"),
                ),
                SkuSnapshot(
                    sku_id="sku-unknown",
                    sku_name="未知",
                    stock=None,
                    price=None,
                ),
            ],
        )
        session.add(snapshot)
        session.commit()

    body = client[0].get(f"/api/competitors/{competitor.id}/detail").json()
    assert body["latest_snapshot"]["min_order_quantity"] == 1
    assert body["latest_skus"] == [
        {
            "sku_id": "sku-known",
            "sku_name": "普通",
            "stock": 3,
            "price": "79.00",
        },
        {
            "sku_id": "sku-unknown",
            "sku_name": "未知",
            "stock": None,
            "price": None,
        },
    ]

    with client[1]() as session:
        current = session.get(ProductSnapshot, snapshot.id)
        assert current is not None
        current.min_order_quantity = None
        session.commit()
    assert client[0].get(f"/api/competitors/{competitor.id}/detail").json()["latest_snapshot"]["min_order_quantity"] is None


def test_detail_decodes_latest_sku_name_and_resolves_exact_stock_change_sku(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    timestamp = datetime.now(timezone.utc) - timedelta(hours=1)
    with client[1]() as session:
        competitor = add_competitor(session)
        snapshot = add_snapshot(session, competitor.id, timestamp, skus=[("sku-pink", 994)])
        snapshot.skus[0].sku_name = " 粉色&gt;A19 "
        add_change(
            session,
            competitor.id,
            snapshot.id,
            "stock_changed",
            timestamp,
            entity_key="sku-pink",
            old_value="998",
            new_value="994",
        )
        session.commit()

    body = client[0].get(f"/api/competitors/{competitor.id}/detail").json()

    assert body["latest_skus"][0]["sku_name"] == "粉色>A19"
    assert body["recent_changes"][0]["sku_name"] == "粉色>A19"


def test_detail_stock_change_uses_historical_sku_name_fallback_and_null_when_missing(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    timestamp = datetime.now(timezone.utc) - timedelta(hours=1)
    with client[1]() as session:
        competitor = add_competitor(session)
        historical = add_snapshot(session, competitor.id, timestamp - timedelta(days=1), skus=[("sku-old", 10)])
        historical.skus[0].sku_name = "卡其色&gt;A19"
        current = add_snapshot(session, competitor.id, timestamp, skus=[])
        add_change(
            session,
            competitor.id,
            current.id,
            "stock_changed",
            timestamp,
            entity_key="sku-old",
            old_value="10",
            new_value="8",
        )
        add_change(
            session,
            competitor.id,
            current.id,
            "stock_changed",
            timestamp + timedelta(minutes=1),
            entity_key="sku-missing",
            old_value="4",
            new_value="3",
        )
        session.commit()

    body = client[0].get(f"/api/competitors/{competitor.id}/detail").json()

    assert body["recent_changes"][0]["sku_name"] is None
    assert body["recent_changes"][1]["sku_name"] == "卡其色>A19"


def test_unknown_stock_and_no_sku_return_null_not_zero(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    today, _, _ = business_day_bounds()
    with client[1]() as session:
        competitor = add_competitor(session)
        add_snapshot(session, competitor.id, utc_for_business_day(today), skus=[("known", 10), ("unknown", None)])
        session.commit()

    body = client[0].get(f"/api/competitors/{competitor.id}/detail").json()

    assert body["latest_snapshot"]["total_stock"] is None
    assert body["daily_trend"][-1]["total_stock"] is None


def test_latest_price_change_ignores_newer_non_price_events_and_preserves_range(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    timestamp = datetime.now(timezone.utc) - timedelta(hours=1)
    with client[1]() as session:
        competitor = add_competitor(session)
        snapshot = add_snapshot(session, competitor.id, timestamp)
        add_change(session, competitor.id, snapshot.id, "price_decrease", timestamp, old_value="40.00~50.00", new_value="38.00~48.00")
        add_change(session, competitor.id, snapshot.id, "stock_changed", timestamp + timedelta(minutes=1), old_value="10", new_value="0")
        add_change(session, competitor.id, snapshot.id, "title_changed", timestamp + timedelta(minutes=2))
        session.commit()

    body = client[0].get(f"/api/competitors/{competitor.id}/detail").json()

    assert body["latest_price_change"]["change_type"] == "price_decrease"
    assert body["latest_price_change"]["old_value"] == "40.00~50.00"
    assert body["latest_price_change"]["new_value"] == "38.00~48.00"


@pytest.mark.parametrize("change_type", ["price_increase", "price_decrease"])
def test_latest_price_change_supports_both_price_directions(
    client: tuple[TestClient, sessionmaker[Session]],
    change_type: str,
) -> None:
    timestamp = datetime.now(timezone.utc) - timedelta(hours=1)
    with client[1]() as session:
        competitor = add_competitor(session)
        snapshot = add_snapshot(session, competitor.id, timestamp)
        add_change(session, competitor.id, snapshot.id, change_type, timestamp, old_value="40.00", new_value="42.00")
        session.commit()

    body = client[0].get(f"/api/competitors/{competitor.id}/detail").json()

    assert body["latest_price_change"]["change_type"] == change_type


def test_no_price_event_returns_null_even_with_recent_other_changes(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    timestamp = datetime.now(timezone.utc) - timedelta(hours=1)
    with client[1]() as session:
        competitor = add_competitor(session)
        snapshot = add_snapshot(session, competitor.id, timestamp)
        add_change(session, competitor.id, snapshot.id, "stock_changed", timestamp, old_value="1", new_value="2")
        add_change(session, competitor.id, snapshot.id, "sku_added", timestamp + timedelta(minutes=1), new_value="红色")
        session.commit()

    body = client[0].get(f"/api/competitors/{competitor.id}/detail").json()

    assert body["latest_price_change"] is None


def test_recent_changes_and_collection_runs_are_limited_and_stably_ordered(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    timestamp = datetime.now(timezone.utc) - timedelta(hours=1)
    with client[1]() as session:
        competitor = add_competitor(session)
        snapshot = add_snapshot(session, competitor.id, timestamp)
        changes = [
            ChangeEvent(
                competitor_id=competitor.id,
                snapshot_id=snapshot.id,
                change_type="stock_changed",
                entity_key=f"sku-{index}",
                detected_at=timestamp,
            )
            for index in range(21)
        ]
        runs = [
            CollectionRun(
                competitor_id=competitor.id,
                started_at=timestamp,
                finished_at=timestamp,
                status="success",
            )
            for _ in range(21)
        ]
        session.add_all([*changes, *runs])
        session.commit()

    query_count = [0]

    def count_query(*_args: object, **_kwargs: object) -> None:
        query_count[0] += 1

    with client[1]() as session:
        engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", count_query)
    try:
        body = client[0].get(f"/api/competitors/{competitor.id}/detail").json()
    finally:
        event.remove(engine, "before_cursor_execute", count_query)

    assert len(body["recent_changes"]) == 20
    assert all("sku_name" in item for item in body["recent_changes"])
    assert query_count[0] <= 10
    assert [item["id"] for item in body["recent_changes"]] == sorted(
        (item["id"] for item in body["recent_changes"]), reverse=True
    )
    assert len(body["recent_collection_runs"]) == 20
    assert [item["id"] for item in body["recent_collection_runs"]] == sorted(
        (item["id"] for item in body["recent_collection_runs"]), reverse=True
    )
    assert "traceback" not in str(body)


def test_inactive_competitor_remains_viewable_and_invalid_days_are_rejected(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    with client[1]() as session:
        competitor = add_competitor(session, active=False)
        session.commit()

    detail = client[0].get(f"/api/competitors/{competitor.id}/detail")
    invalid = client[0].get(f"/api/competitors/{competitor.id}/detail?days=14")

    assert detail.status_code == 200
    assert detail.json()["competitor"]["is_active"] is False
    assert detail.json()["competitor"]["status"] == "offline"
    assert invalid.status_code == 422
