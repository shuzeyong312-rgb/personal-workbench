from collections.abc import Generator
from datetime import date, datetime, timedelta, timezone
import importlib
import zoneinfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.dashboard as dashboard
from app.database import get_db
from app.main import app
from app.models import Base, ChangeEvent, CollectionRun, Competitor, CompetitorGroup, ProductSnapshot, SkuSnapshot


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


BUSINESS_DATE = date(2026, 9, 20)
START_UTC = datetime(2026, 9, 19, 16)
END_UTC = datetime(2026, 9, 20, 16)


def test_business_day_bounds_converts_asia_shanghai_to_utc() -> None:
    business_date, start_utc, end_utc = dashboard.business_day_bounds(
        datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
    )

    assert business_date == date(2026, 9, 20)
    assert start_utc == datetime(2026, 9, 19, 16)
    assert end_utc == datetime(2026, 9, 20, 16)
    assert start_utc.tzinfo is None
    assert end_utc.tzinfo is None


def test_business_day_bounds_uses_utc_plus_8_when_zoneinfo_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(_key: str) -> zoneinfo.ZoneInfo:
        raise zoneinfo.ZoneInfoNotFoundError(_key)

    try:
        with monkeypatch.context() as context:
            context.setattr(zoneinfo, "ZoneInfo", unavailable)
            importlib.reload(dashboard)
            _, start_utc, end_utc = dashboard.business_day_bounds(
                datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
            )
            assert start_utc == datetime(2026, 9, 19, 16)
            assert end_utc == datetime(2026, 9, 20, 16)
    finally:
        importlib.reload(dashboard)


@pytest.fixture()
def business_day(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        dashboard,
        "business_day_bounds",
        lambda: (BUSINESS_DATE, START_UTC, END_UTC),
    )


def add_competitor(
    session: Session, competitor_id: int, *, active: bool = True, group_id: int | None = None
) -> Competitor:
    detected_at = datetime(2026, 9, 20, 1)
    competitor = Competitor(
        id=competitor_id,
        group_id=group_id,
        platform="1688",
        offer_id=str(competitor_id),
        url=f"https://detail.1688.com/offer/{competitor_id}.html",
        title=f"商品 {competitor_id}",
        shop_name=f"店铺 {competitor_id}",
        main_image_url=None,
        status="active" if active else "offline",
        is_active=active,
        created_at=detected_at,
        updated_at=detected_at,
        last_collected_at=detected_at,
    )
    session.add(competitor)
    session.flush()
    return competitor


def add_event(
    session: Session,
    competitor: Competitor,
    detected_at: datetime,
    change_type: str,
    *,
    entity_key: str | None = None,
    old_value: str = "1.00",
    new_value: str = "2.00",
    sku_name: str | None = None,
) -> ChangeEvent:
    snapshot = ProductSnapshot(
        competitor_id=competitor.id,
        captured_at=detected_at,
        title=competitor.title or "",
        shop_name=competitor.shop_name or "",
        product_status="active",
        collection_source="html",
    )
    session.add(snapshot)
    session.flush()
    if entity_key is not None and sku_name is not None:
        session.add(
            SkuSnapshot(
                product_snapshot_id=snapshot.id,
                sku_id=entity_key,
                sku_name=sku_name,
                stock=int(float(new_value)) if change_type == "stock_changed" else None,
            )
        )
        session.flush()
    event = ChangeEvent(
        competitor_id=competitor.id,
        snapshot_id=snapshot.id,
        change_type=change_type,
        entity_key=entity_key,
        old_value=old_value,
        new_value=new_value,
        detected_at=detected_at,
    )
    session.add(event)
    session.flush()
    return event


def add_snapshot_with_stocks(
    session: Session,
    competitor: Competitor,
    captured_at: datetime,
    stocks: list[int | None],
) -> ProductSnapshot:
    snapshot = ProductSnapshot(
        competitor_id=competitor.id,
        captured_at=captured_at,
        title=competitor.title or "",
        shop_name=competitor.shop_name or "",
        product_status="active",
        collection_source="html",
    )
    snapshot.skus = [
        SkuSnapshot(sku_id=f"sku-{index}", sku_name=f"SKU {index}", stock=stock)
        for index, stock in enumerate(stocks)
    ]
    session.add(snapshot)
    session.flush()
    return snapshot


def add_event_on_snapshot(
    session: Session,
    competitor: Competitor,
    snapshot: ProductSnapshot,
    detected_at: datetime,
    *,
    entity_key: str = "sku-0",
    old_value: str = "1",
    new_value: str = "2",
) -> ChangeEvent:
    change = ChangeEvent(
        competitor_id=competitor.id,
        snapshot_id=snapshot.id,
        change_type="stock_changed",
        entity_key=entity_key,
        old_value=old_value,
        new_value=new_value,
        detected_at=detected_at,
    )
    session.add(change)
    session.flush()
    return change


def add_run(
    session: Session,
    competitor: Competitor,
    started_at: datetime,
    status: str,
    finished_at: datetime | None = None,
) -> CollectionRun:
    run = CollectionRun(
        competitor_id=competitor.id,
        started_at=started_at,
        finished_at=finished_at,
        status=status,
    )
    session.add(run)
    session.flush()
    return run


def test_today_without_events_returns_empty_stats(
    client: tuple[TestClient, sessionmaker[Session]], business_day: None
) -> None:
    with client[1]() as session:
        add_competitor(session, 1)
        session.commit()

    body = client[0].get("/api/dashboard/today").json()

    assert body["date"] == "2026-09-20"
    assert body["stats"] == {
        "monitored_competitors": 1,
        "changed_competitors": 0,
        "change_events": 0,
        "price_changed_competitors": 0,
        "stock_changed_competitors": 0,
        "sku_changed_competitors": 0,
        "failed_collections": 0,
    }
    assert body["items"] == []
    assert body["collection_summary"] == {
        "last_collection_at": None,
        "success_runs": 0,
        "failed_runs": 0,
        "average_duration_seconds": None,
    }
    assert len(body["trend_7d"]) == 7
    assert all(point["price_changes"] == 0 for point in body["trend_7d"])


def test_groups_two_events_for_one_active_competitor(
    client: tuple[TestClient, sessionmaker[Session]], business_day: None
) -> None:
    with client[1]() as session:
        session.add(CompetitorGroup(id=7, name="家居用品组", created_at=datetime(2026, 9, 19)))
        session.flush()
        competitor = add_competitor(session, 1, group_id=7)
        first = add_event(session, competitor, datetime(2026, 9, 20, 1), "title_changed")
        second = add_event(session, competitor, datetime(2026, 9, 20, 2), "price_increase")
        session.commit()

    body = client[0].get("/api/dashboard/today").json()

    assert body["stats"] == {
        "monitored_competitors": 1,
        "changed_competitors": 1,
        "change_events": 2,
        "price_changed_competitors": 1,
        "stock_changed_competitors": 0,
        "sku_changed_competitors": 0,
        "failed_collections": 0,
    }
    assert len(body["items"]) == 1
    assert body["items"][0]["competitor_id"] == 1
    assert body["items"][0]["change_count"] == 2
    assert body["items"][0]["change_types"] == ["price_increase", "title_changed"]
    assert body["items"][0]["primary_change"]["id"] == second.id
    assert body["items"][0]["group_id"] == 7


def test_returns_two_items_in_latest_event_order(
    client: tuple[TestClient, sessionmaker[Session]], business_day: None
) -> None:
    with client[1]() as session:
        first_competitor = add_competitor(session, 1)
        second_competitor = add_competitor(session, 2)
        add_event(session, first_competitor, datetime(2026, 9, 20, 1), "title_changed")
        newest = add_event(session, second_competitor, datetime(2026, 9, 20, 2), "sku_added")
        session.commit()

    items = client[0].get("/api/dashboard/today").json()["items"]

    assert [item["competitor_id"] for item in items] == [2, 1]
    assert items[0]["latest_change_at"] == "2026-09-20T02:00:00"
    assert items[0]["primary_change"]["id"] == newest.id


def test_orders_same_timestamp_events_and_items_by_id_desc(
    client: tuple[TestClient, sessionmaker[Session]], business_day: None
) -> None:
    detected_at = datetime(2026, 9, 20, 2)
    with client[1]() as session:
        first_competitor = add_competitor(session, 1)
        second_competitor = add_competitor(session, 2)
        first_event = add_event(session, first_competitor, detected_at, "title_changed")
        add_event(session, second_competitor, detected_at, "sku_added")
        newest_first_event = add_event(session, first_competitor, detected_at, "price_increase")
        session.commit()

    body = client[0].get("/api/dashboard/today").json()

    assert [item["competitor_id"] for item in body["items"]] == [2, 1]
    assert body["items"][1]["primary_change"]["id"] == newest_first_event.id


def test_excludes_yesterday_and_boundary_belongs_to_local_today(
    client: tuple[TestClient, sessionmaker[Session]], business_day: None
) -> None:
    with client[1]() as session:
        competitor = add_competitor(session, 1)
        add_event(session, competitor, START_UTC - timedelta(seconds=1), "title_changed")
        boundary = add_event(session, competitor, START_UTC, "main_image_changed")
        add_event(session, competitor, END_UTC, "stock_changed")
        session.commit()

    item = client[0].get("/api/dashboard/today").json()["items"][0]

    assert item["change_count"] == 1
    assert item["primary_change"]["id"] == boundary.id


def test_excludes_inactive_competitor_even_with_today_event(
    client: tuple[TestClient, sessionmaker[Session]], business_day: None
) -> None:
    with client[1]() as session:
        competitor = add_competitor(session, 1, active=False)
        add_event(session, competitor, datetime(2026, 9, 20, 1), "title_changed")
        active = add_competitor(session, 2)
        add_event(session, active, datetime(2026, 9, 20, 2), "title_changed")
        session.commit()

    body = client[0].get("/api/dashboard/today").json()

    assert body["stats"]["monitored_competitors"] == 1
    assert body["stats"]["change_events"] == 1
    assert [item["competitor_id"] for item in body["items"]] == [2]


def test_today_stats_count_distinct_active_competitors_by_change_type_and_failed_runs(
    client: tuple[TestClient, sessionmaker[Session]], business_day: None
) -> None:
    with client[1]() as session:
        first = add_competitor(session, 1)
        second = add_competitor(session, 2)
        inactive = add_competitor(session, 3, active=False)
        add_event(session, first, datetime(2026, 9, 20, 1), "price_increase")
        add_event(session, first, datetime(2026, 9, 20, 2), "price_decrease")
        add_event(session, first, datetime(2026, 9, 20, 3), "stock_changed")
        add_event(session, second, datetime(2026, 9, 20, 4), "sku_added")
        add_event(session, second, datetime(2026, 9, 20, 5), "sku_removed")
        add_event(session, inactive, datetime(2026, 9, 20, 6), "main_image_changed")
        add_run(session, first, datetime(2026, 9, 20, 7), "failed", datetime(2026, 9, 20, 7, 0, 3))
        add_run(session, second, datetime(2026, 9, 20, 8), "failed", datetime(2026, 9, 20, 8, 0, 4))
        session.commit()

    stats = client[0].get("/api/dashboard/today").json()["stats"]

    assert stats["price_changed_competitors"] == 1
    assert stats["stock_changed_competitors"] == 1
    assert stats["sku_changed_competitors"] == 1
    assert stats["failed_collections"] == 2
    assert stats["changed_competitors"] == 2


def test_collection_summary_uses_today_runs_and_ignores_unfinished_for_average(
    client: tuple[TestClient, sessionmaker[Session]], business_day: None
) -> None:
    with client[1]() as session:
        competitor = add_competitor(session, 1)
        yesterday = add_run(session, competitor, START_UTC - timedelta(seconds=1), "success", START_UTC)
        today_success = add_run(session, competitor, datetime(2026, 9, 20, 1), "success", datetime(2026, 9, 20, 1, 0, 10))
        add_run(session, competitor, datetime(2026, 9, 20, 2), "failed", datetime(2026, 9, 20, 2, 0, 20))
        add_run(session, competitor, datetime(2026, 9, 20, 3), "running")
        session.commit()

    body = client[0].get("/api/dashboard/today").json()

    assert body["stats"]["failed_collections"] == 1
    assert body["collection_summary"] == {
        "last_collection_at": "2026-09-20T02:00:20",
        "success_runs": 1,
        "failed_runs": 1,
        "average_duration_seconds": 15.0,
    }
    assert yesterday.id != today_success.id


def test_trend_returns_contiguous_business_dates_with_event_categories_and_failed_runs(
    client: tuple[TestClient, sessionmaker[Session]], business_day: None
) -> None:
    with client[1]() as session:
        competitor = add_competitor(session, 1)
        add_event(session, competitor, datetime(2026, 9, 19, 15, 59, 59), "price_increase")
        add_event(session, competitor, datetime(2026, 9, 19, 16), "price_decrease")
        add_event(session, competitor, datetime(2026, 9, 20, 15, 59, 59), "stock_changed")
        add_event(session, competitor, datetime(2026, 9, 20, 16), "sku_added")
        add_run(session, competitor, datetime(2026, 9, 20, 15, 59, 59), "failed")
        add_run(session, competitor, datetime(2026, 9, 20, 16), "failed")
        session.commit()

    trend = client[0].get("/api/dashboard/today").json()["trend_7d"]

    assert [point["date"] for point in trend] == [
        "2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18", "2026-09-19", "2026-09-20",
    ]
    assert trend[-2] == {
        "date": "2026-09-19",
        "price_changes": 1,
        "stock_changes": 0,
        "sku_changes": 0,
        "failed_collections": 0,
    }
    assert trend[-1] == {
        "date": "2026-09-20",
        "price_changes": 1,
        "stock_changes": 1,
        "sku_changes": 0,
        "failed_collections": 1,
    }


def test_returns_contract_fields_without_group_name(
    client: tuple[TestClient, sessionmaker[Session]], business_day: None
) -> None:
    with client[1]() as session:
        competitor = add_competitor(session, 1)
        add_event(session, competitor, datetime(2026, 9, 20, 1), "stock_changed")
        session.commit()

    body = client[0].get("/api/dashboard/today").json()
    item = body["items"][0]

    assert set(item) == {
        "competitor_id",
        "title",
        "shop_name",
        "main_image_url",
        "group_id",
        "last_collected_at",
        "change_count",
        "change_types",
        "latest_change_at",
        "primary_change",
        "stock_changed_sku_count",
        "stock_total_change",
        "sku_added_count",
        "sku_removed_count",
    }
    assert "group_name" not in item
    assert set(item["primary_change"]) == {
        "id",
        "change_type",
        "entity_key",
        "sku_name",
        "old_value",
        "new_value",
        "detected_at",
    }


def test_aggregates_same_sku_stock_events_and_uses_latest_summary(
    client: tuple[TestClient, sessionmaker[Session]], business_day: None
) -> None:
    with client[1]() as session:
        competitor = add_competitor(session, 1)
        add_event(session, competitor, datetime(2026, 9, 20, 1), "stock_changed", entity_key="sku-1", old_value="100", new_value="90", sku_name="白色款")
        latest = add_event(session, competitor, datetime(2026, 9, 20, 2), "stock_changed", entity_key="sku-1", old_value="90", new_value="80", sku_name="白色款")
        session.commit()

    item = client[0].get("/api/dashboard/today").json()["items"][0]

    assert item["change_count"] == 2
    assert item["stock_changed_sku_count"] == 1
    assert item["primary_change"]["id"] == latest.id
    assert item["primary_change"]["sku_name"] == "白色款"


def test_stock_primary_returns_single_sku_snapshot_total_change(
    client: tuple[TestClient, sessionmaker[Session]], business_day: None
) -> None:
    with client[1]() as session:
        competitor = add_competitor(session, 1)
        add_snapshot_with_stocks(session, competitor, datetime(2026, 9, 20, 1), [998])
        current = add_snapshot_with_stocks(session, competitor, datetime(2026, 9, 20, 2), [994])
        add_event_on_snapshot(session, competitor, current, datetime(2026, 9, 20, 2), old_value="998", new_value="994")
        session.commit()

    item = client[0].get("/api/dashboard/today").json()["items"][0]

    assert item["stock_total_change"] == {"old_total": 998, "new_total": 994}


def test_stock_primary_sums_all_skus_and_preserves_zero(
    client: tuple[TestClient, sessionmaker[Session]], business_day: None
) -> None:
    with client[1]() as session:
        competitor = add_competitor(session, 1)
        add_snapshot_with_stocks(session, competitor, datetime(2026, 9, 20, 1), [0, 10, 20])
        current = add_snapshot_with_stocks(session, competitor, datetime(2026, 9, 20, 2), [0, 10, 17])
        add_event_on_snapshot(session, competitor, current, datetime(2026, 9, 20, 2), entity_key="sku-2", old_value="20", new_value="17")
        session.commit()

    item = client[0].get("/api/dashboard/today").json()["items"][0]

    assert item["stock_total_change"] == {"old_total": 30, "new_total": 27}


@pytest.mark.parametrize(
    ("previous_stocks", "current_stocks", "expected"),
    [
        (None, [9], {"old_total": None, "new_total": 9}),
        ([], [9], {"old_total": None, "new_total": 9}),
        ([None], [9], {"old_total": None, "new_total": 9}),
        ([9], [None], {"old_total": 9, "new_total": None}),
    ],
)
def test_stock_total_change_preserves_unknown_snapshot_totals(
    client: tuple[TestClient, sessionmaker[Session]],
    business_day: None,
    previous_stocks: list[int | None] | None,
    current_stocks: list[int | None],
    expected: dict[str, int | None],
) -> None:
    with client[1]() as session:
        competitor = add_competitor(session, 1)
        if previous_stocks is not None:
            add_snapshot_with_stocks(session, competitor, datetime(2026, 9, 20, 1), previous_stocks)
        current = add_snapshot_with_stocks(session, competitor, datetime(2026, 9, 20, 2), current_stocks)
        add_event_on_snapshot(session, competitor, current, datetime(2026, 9, 20, 2))
        session.commit()

    item = client[0].get("/api/dashboard/today").json()["items"][0]

    assert item["stock_total_change"] == expected


def test_stock_total_uses_event_snapshot_not_later_no_change_snapshot(
    client: tuple[TestClient, sessionmaker[Session]], business_day: None
) -> None:
    with client[1]() as session:
        competitor = add_competitor(session, 1)
        add_snapshot_with_stocks(session, competitor, datetime(2026, 9, 20, 1), [100])
        event_snapshot = add_snapshot_with_stocks(session, competitor, datetime(2026, 9, 20, 2), [90])
        add_event_on_snapshot(session, competitor, event_snapshot, datetime(2026, 9, 20, 2), old_value="100", new_value="90")
        add_snapshot_with_stocks(session, competitor, datetime(2026, 9, 20, 3), [80])
        session.commit()

    item = client[0].get("/api/dashboard/today").json()["items"][0]

    assert item["stock_total_change"] == {"old_total": 100, "new_total": 90}


def test_stock_total_previous_snapshot_uses_id_tie_break(
    client: tuple[TestClient, sessionmaker[Session]], business_day: None
) -> None:
    captured_at = datetime(2026, 9, 20, 1)
    with client[1]() as session:
        competitor = add_competitor(session, 1)
        add_snapshot_with_stocks(session, competitor, captured_at, [10])
        second_previous = add_snapshot_with_stocks(session, competitor, captured_at, [20])
        current = add_snapshot_with_stocks(session, competitor, datetime(2026, 9, 20, 2), [30])
        add_event_on_snapshot(session, competitor, current, datetime(2026, 9, 20, 2), old_value="20", new_value="30")
        session.commit()

    item = client[0].get("/api/dashboard/today").json()["items"][0]

    assert second_previous.id > 0
    assert item["stock_total_change"] == {"old_total": 20, "new_total": 30}


def test_multiple_stock_events_use_latest_primary_snapshot_pair(
    client: tuple[TestClient, sessionmaker[Session]], business_day: None
) -> None:
    with client[1]() as session:
        competitor = add_competitor(session, 1)
        add_snapshot_with_stocks(session, competitor, datetime(2026, 9, 20, 1), [120])
        first_current = add_snapshot_with_stocks(session, competitor, datetime(2026, 9, 20, 2), [100])
        add_event_on_snapshot(session, competitor, first_current, datetime(2026, 9, 20, 2), old_value="120", new_value="100")
        latest = add_snapshot_with_stocks(session, competitor, datetime(2026, 9, 20, 3), [90])
        add_event_on_snapshot(session, competitor, latest, datetime(2026, 9, 20, 3), old_value="100", new_value="90")
        session.commit()

    item = client[0].get("/api/dashboard/today").json()["items"][0]

    assert item["stock_total_change"] == {"old_total": 100, "new_total": 90}


def test_stock_total_queries_are_batched_for_multiple_competitors(
    client: tuple[TestClient, sessionmaker[Session]], business_day: None
) -> None:
    with client[1]() as session:
        for competitor_id in range(1, 4):
            competitor = add_competitor(session, competitor_id)
            add_snapshot_with_stocks(session, competitor, datetime(2026, 9, 20, 1), [10])
            current = add_snapshot_with_stocks(session, competitor, datetime(2026, 9, 20, 2), [9])
            add_event_on_snapshot(session, competitor, current, datetime(2026, 9, 20, 2), old_value="10", new_value="9")
        session.commit()

    query_count = [0]

    def count_query(*_args: object, **_kwargs: object) -> None:
        query_count[0] += 1

    with client[1]() as session:
        engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", count_query)
    try:
        body = client[0].get("/api/dashboard/today").json()
    finally:
        event.remove(engine, "before_cursor_execute", count_query)

    assert len(body["items"]) == 3
    assert query_count[0] <= 12


def test_decodes_html_entities_in_recovered_sku_name(
    client: tuple[TestClient, sessionmaker[Session]], business_day: None
) -> None:
    with client[1]() as session:
        competitor = add_competitor(session, 1)
        add_event(
            session,
            competitor,
            datetime(2026, 9, 20, 1),
            "stock_changed",
            entity_key="sku-1",
            old_value="100",
            new_value="90",
            sku_name="粉色&gt;A19",
        )
        session.commit()

    primary = client[0].get("/api/dashboard/today").json()["items"][0]["primary_change"]

    assert primary["sku_name"] == "粉色>A19"


def test_aggregates_different_sku_stock_events_by_distinct_sku(
    client: tuple[TestClient, sessionmaker[Session]], business_day: None
) -> None:
    with client[1]() as session:
        competitor = add_competitor(session, 1)
        add_event(session, competitor, datetime(2026, 9, 20, 1), "stock_changed", entity_key="sku-1", sku_name="白色款")
        add_event(session, competitor, datetime(2026, 9, 20, 2), "stock_changed", entity_key="sku-2", sku_name="黑色款")
        session.commit()

    item = client[0].get("/api/dashboard/today").json()["items"][0]

    assert item["change_count"] == 2
    assert item["stock_changed_sku_count"] == 2


def test_stock_primary_keeps_sku_id_when_name_cannot_be_recovered(
    client: tuple[TestClient, sessionmaker[Session]], business_day: None
) -> None:
    with client[1]() as session:
        competitor = add_competitor(session, 1)
        add_event(session, competitor, datetime(2026, 9, 20, 1), "stock_changed", entity_key="sku-unknown", old_value="10", new_value="8")
        session.commit()

    primary = client[0].get("/api/dashboard/today").json()["items"][0]["primary_change"]

    assert primary["entity_key"] == "sku-unknown"
    assert primary["sku_name"] is None


def test_primary_priority_and_counts_preserve_all_change_types(
    client: tuple[TestClient, sessionmaker[Session]], business_day: None
) -> None:
    with client[1]() as session:
        competitor = add_competitor(session, 1)
        add_event(session, competitor, datetime(2026, 9, 20, 1), "stock_changed", entity_key="sku-1", sku_name="白色款")
        price = add_event(session, competitor, datetime(2026, 9, 20, 2), "price_decrease", old_value="40.00", new_value="38.00")
        add_event(session, competitor, datetime(2026, 9, 20, 3), "sku_added", entity_key="sku-2", new_value="蓝色款")
        add_event(
            session,
            competitor,
            datetime(2026, 9, 20, 4),
            "main_image_changed",
            old_value="https://img.example.com/a.jpg",
            new_value="https://img.example.com/b.jpg",
        )
        add_event(session, competitor, datetime(2026, 9, 20, 5), "title_changed", old_value="旧标题", new_value="新标题")
        session.commit()

    item = client[0].get("/api/dashboard/today").json()["items"][0]

    assert item["change_count"] == 5
    assert item["change_types"] == ["price_decrease", "stock_changed", "sku_added", "main_image_changed", "title_changed"]
    assert item["primary_change"]["id"] == price.id


def test_lifecycle_changes_have_frozen_dashboard_priority(
    client: tuple[TestClient, sessionmaker[Session]], business_day: None
) -> None:
    with client[1]() as session:
        competitor = add_competitor(session, 1)
        offline = ChangeEvent(
            competitor_id=competitor.id,
            snapshot_id=None,
            change_type="product_offline",
            old_value="active",
            new_value="offline",
            detected_at=datetime(2026, 9, 20, 3),
        )
        session.add(offline)
        session.flush()
        add_event(session, competitor, datetime(2026, 9, 20, 6), "price_decrease")
        online = add_event(session, competitor, datetime(2026, 9, 20, 5), "product_online")
        session.commit()

    item = client[0].get("/api/dashboard/today").json()["items"][0]

    assert item["change_types"] == ["product_offline", "product_online", "price_decrease"]
    assert item["primary_change"]["change_type"] == "product_online"
    assert item["primary_change"]["id"] == online.id
    assert online.id > offline.id


def test_newer_offline_event_wins_over_older_online_event(
    client: tuple[TestClient, sessionmaker[Session]], business_day: None
) -> None:
    with client[1]() as session:
        competitor = add_competitor(session, 1)
        add_event(
            session,
            competitor,
            datetime(2026, 9, 20, 3),
            "product_online",
            old_value="offline",
            new_value="active",
        )
        session.add(
            ChangeEvent(
                competitor_id=competitor.id,
                snapshot_id=None,
                change_type="product_offline",
                old_value="active",
                new_value="offline",
                detected_at=datetime(2026, 9, 20, 5),
            )
        )
        session.commit()

    primary = client[0].get("/api/dashboard/today").json()["items"][0]["primary_change"]

    assert primary["change_type"] == "product_offline"


def test_same_timestamp_lifecycle_events_use_id_desc(
    client: tuple[TestClient, sessionmaker[Session]], business_day: None
) -> None:
    timestamp = datetime(2026, 9, 20, 5)
    with client[1]() as session:
        competitor = add_competitor(session, 1)
        add_event(
            session,
            competitor,
            timestamp,
            "product_online",
            old_value="offline",
            new_value="active",
        )
        session.add(
            ChangeEvent(
                competitor_id=competitor.id,
                snapshot_id=None,
                change_type="product_offline",
                old_value="active",
                new_value="offline",
                detected_at=timestamp,
            )
        )
        session.commit()
        events = session.scalars(select(ChangeEvent).order_by(ChangeEvent.id)).all()

    primary = client[0].get("/api/dashboard/today").json()["items"][0]["primary_change"]

    assert primary["id"] == events[1].id
    assert primary["change_type"] == "product_offline"


def test_main_image_primary_is_above_title_and_keeps_one_competitor_row(
    client: tuple[TestClient, sessionmaker[Session]], business_day: None
) -> None:
    with client[1]() as session:
        competitor = add_competitor(session, 1)
        add_event(
            session,
            competitor,
            datetime(2026, 9, 20, 1),
            "title_changed",
            old_value="旧标题",
            new_value="新标题",
        )
        main_image = add_event(
            session,
            competitor,
            datetime(2026, 9, 20, 2),
            "main_image_changed",
            old_value="https://img.example.com/a.jpg",
            new_value="https://img.example.com/b.jpg",
        )
        session.commit()

    body = client[0].get("/api/dashboard/today").json()

    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["change_types"] == ["main_image_changed", "title_changed"]
    assert item["primary_change"]["id"] == main_image.id
    assert item["primary_change"]["change_type"] == "main_image_changed"
    assert item["primary_change"]["old_value"] == "https://img.example.com/a.jpg"
    assert item["primary_change"]["new_value"] == "https://img.example.com/b.jpg"


def test_multiple_price_events_use_latest_price_event(
    client: tuple[TestClient, sessionmaker[Session]], business_day: None
) -> None:
    with client[1]() as session:
        competitor = add_competitor(session, 1)
        add_event(session, competitor, datetime(2026, 9, 20, 1), "price_decrease", old_value="40.00", new_value="39.00")
        latest = add_event(session, competitor, datetime(2026, 9, 20, 2), "price_decrease", old_value="39.00", new_value="38.00")
        session.commit()

    primary = client[0].get("/api/dashboard/today").json()["items"][0]["primary_change"]

    assert primary["id"] == latest.id
    assert primary["old_value"] == "39.00"
    assert primary["new_value"] == "38.00"
