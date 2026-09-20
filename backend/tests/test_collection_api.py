from collections.abc import Generator
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.collection.collector_1688 import (
    CollectionTimeoutError,
    LoginRequiredError,
    PageUnavailableError,
    VerificationRequiredError,
)
from app.collection.parser_1688 import CollectionParseError, OfferIdMismatchError
from app.collection.service import COLLECTION_LOCK
from app.collection.types import ProductData, SkuData
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


def add_competitor(
    session_factory: sessionmaker[Session], offer_id: str = "1081895898799", group_id: int | None = None
) -> int:
    now = datetime(2026, 9, 19, tzinfo=timezone.utc)
    with session_factory() as session:
        competitor = Competitor(
            platform="1688",
            offer_id=offer_id,
            group_id=group_id,
            url=f"https://detail.1688.com/offer/{offer_id}.html",
            title="旧标题",
            shop_name="旧店铺",
            main_image_url="https://example.com/old.jpg",
            status="active",
            is_active=True,
            created_at=now,
            updated_at=now,
            last_collected_at=now,
        )
        session.add(competitor)
        session.commit()
        return competitor.id


def product(offer_id: str = "1081895898799", captured_at: datetime | None = None) -> ProductData:
    return ProductData(
        offer_id=offer_id,
        title="新商品标题",
        shop_name="新店铺",
        main_image_url="https://example.com/product.jpg",
        price_min=Decimal("40.00"),
        price_max=Decimal("42.00"),
        product_status="unknown",
        collection_source="html",
        captured_at=captured_at or datetime(2026, 9, 19, 1, tzinfo=timezone.utc),
        skus=[
            SkuData("sku-1", "红色", 3, None),
            SkuData("sku-2", "蓝色", None, Decimal("41.00")),
            SkuData("sku-3", "绿色", 0, None),
        ],
    )


def test_missing_competitor_does_not_collect_or_create_run(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    with patch("app.collection.service.collect_1688_product") as collector:
        response = client[0].post("/api/competitors/999/collect")

    assert response.status_code == 404
    assert response.json() == {"code": "competitor_not_found", "message": "竞品不存在"}
    collector.assert_not_called()
    with client[1]() as session:
        assert session.scalar(select(CollectionRun)) is None


def test_busy_lock_returns_409_without_collecting_or_creating_run(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    competitor_id = add_competitor(client[1])
    COLLECTION_LOCK.acquire()
    try:
        with patch("app.collection.service.collect_1688_product") as collector:
            response = client[0].post(f"/api/competitors/{competitor_id}/collect")
    finally:
        COLLECTION_LOCK.release()

    assert response.status_code == 409
    assert response.json()["code"] == "collection_in_progress"
    collector.assert_not_called()
    with client[1]() as session:
        assert session.scalar(select(CollectionRun)) is None


def test_success_persists_run_snapshot_skus_and_competitor(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    competitor_id = add_competitor(client[1])
    collected = product()
    with patch("app.collection.service.collect_1688_product", return_value=collected) as collector:
        response = client[0].post(f"/api/competitors/{competitor_id}/collect")

    assert response.status_code == 200
    collector.assert_called_once_with(
        "https://detail.1688.com/offer/1081895898799.html", "1081895898799"
    )
    body = response.json()
    assert body["snapshot"]["price_min"] == "40.00"
    assert body["snapshot"]["price_max"] == "42.00"
    assert body["snapshot"]["sku_count"] == 3
    assert body["collection_run"]["status"] == "success"
    assert body["competitor"]["latest_change"] is None

    with client[1]() as session:
        saved_competitor = session.get(Competitor, competitor_id)
        assert saved_competitor is not None
        assert saved_competitor.title == "新商品标题"
        assert saved_competitor.shop_name == "新店铺"
        assert saved_competitor.status == "unknown"
        assert saved_competitor.last_collected_at == collected.captured_at.replace(tzinfo=None)
        snapshot = session.scalar(select(ProductSnapshot))
        assert snapshot is not None
        assert len(session.scalars(select(SkuSnapshot)).all()) == 3
        run = session.scalar(select(CollectionRun))
        assert run is not None
        assert run.status == "success"
        assert run.error_type is None
        assert run.error_message is None


def test_collection_response_and_persistence_keep_competitor_group(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    with client[1]() as session:
        group = CompetitorGroup(name="暖手宝", created_at=datetime.now(timezone.utc))
        session.add(group)
        session.flush()
        group_id = group.id
        session.commit()
    competitor_id = add_competitor(client[1], group_id=group_id)

    with patch("app.collection.service.collect_1688_product", return_value=product()):
        response = client[0].post(f"/api/competitors/{competitor_id}/collect")

    assert response.status_code == 200
    assert response.json()["competitor"]["group_id"] == group_id
    with client[1]() as session:
        assert session.get(Competitor, competitor_id).group_id == group_id


def test_repeated_collection_adds_snapshot_and_latest_listing_projection(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    competitor_id = add_competitor(client[1])
    first = product(captured_at=datetime(2026, 9, 19, 1, tzinfo=timezone.utc))
    second = product(captured_at=datetime(2026, 9, 19, 2, tzinfo=timezone.utc))
    with patch("app.collection.service.collect_1688_product", side_effect=[first, second]):
        assert client[0].post(f"/api/competitors/{competitor_id}/collect").status_code == 200
        assert client[0].post(f"/api/competitors/{competitor_id}/collect").status_code == 200

    body = client[0].get("/api/competitors").json()
    assert body[0]["latest_snapshot"] == {
        "price_min": "40.00",
        "price_max": "42.00",
        "sku_count": 3,
    }
    assert body[0]["latest_change"] is None
    assert "latest_collection_run" not in body[0]
    with client[1]() as session:
        assert session.query(ProductSnapshot).count() == 2
        assert session.query(SkuSnapshot).count() == 6
        assert session.query(ChangeEvent).count() == 0


def test_collect_without_new_changes_keeps_historical_latest_change(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    competitor_id = add_competitor(client[1])
    collected = product(captured_at=datetime(2026, 9, 19, 2, tzinfo=timezone.utc))
    with client[1]() as session:
        previous = ProductSnapshot(
            competitor_id=competitor_id,
            captured_at=datetime(2026, 9, 19, 1, tzinfo=timezone.utc),
            title=collected.title,
            shop_name=collected.shop_name,
            main_image_url=collected.main_image_url,
            price_min=collected.price_min,
            price_max=collected.price_max,
            product_status=collected.product_status,
            collection_source=collected.collection_source,
            skus=[
                SkuSnapshot(
                    sku_id=sku.sku_id,
                    sku_name=sku.sku_name,
                    stock=sku.stock,
                    price=sku.price,
                )
                for sku in collected.skus
            ],
        )
        session.add(previous)
        session.flush()
        historical_change = ChangeEvent(
            competitor_id=competitor_id,
            snapshot_id=previous.id,
            change_type="price_increase",
            old_value="35.00",
            new_value="40.00",
            detected_at=datetime(2026, 9, 19, 1, 30, tzinfo=timezone.utc),
        )
        session.add(historical_change)
        session.commit()
        previous_snapshot_id = previous.id
        historical_change_id = historical_change.id

    with patch("app.collection.service.collect_1688_product", return_value=collected):
        response = client[0].post(f"/api/competitors/{competitor_id}/collect")

    assert response.status_code == 200
    body = response.json()
    assert body["snapshot"]["sku_count"] == 3
    assert body["collection_run"]["status"] == "success"
    latest_change = body["competitor"]["latest_change"]
    assert latest_change is not None
    assert latest_change["id"] == historical_change_id
    assert latest_change["change_type"] == "price_increase"
    assert latest_change["old_value"] == "35.00"
    assert latest_change["new_value"] == "40.00"
    assert latest_change["snapshot_id"] == previous_snapshot_id
    assert body["snapshot"]["id"] != latest_change["snapshot_id"]

    with client[1]() as session:
        assert session.query(ProductSnapshot).count() == 2
        assert session.query(SkuSnapshot).count() == 6
        assert session.query(ChangeEvent).count() == 1
        saved_change = session.scalar(select(ChangeEvent))
        assert saved_change is not None
        assert saved_change.id == historical_change_id
        assert saved_change.snapshot_id == previous_snapshot_id


def test_collection_persists_all_changes_against_latest_tied_snapshot(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    competitor_id = add_competitor(client[1])
    captured_at = datetime(2026, 9, 19, 1, tzinfo=timezone.utc)
    with client[1]() as session:
        session.add_all(
            [
                ProductSnapshot(
                    competitor_id=competitor_id,
                    captured_at=captured_at,
                    title="最早标题",
                    shop_name="旧店铺",
                    price_min=Decimal("10.00"),
                    price_max=Decimal("12.00"),
                    product_status="active",
                    collection_source="html",
                ),
                ProductSnapshot(
                    competitor_id=competitor_id,
                    captured_at=captured_at,
                    title="基线标题",
                    shop_name="旧店铺",
                    price_min=Decimal("40.00"),
                    price_max=Decimal("42.00"),
                    product_status="active",
                    collection_source="html",
                    skus=[
                        SkuSnapshot(sku_id="sku-keep", sku_name="保留", stock=3, price=None),
                        SkuSnapshot(sku_id="sku-remove", sku_name="删除", stock=1, price=None),
                    ],
                ),
            ]
        )
        session.commit()
        snapshots = session.scalars(
            select(ProductSnapshot).where(ProductSnapshot.competitor_id == competitor_id)
        ).all()
        baseline = max(snapshots, key=lambda item: item.id)

    current = replace(
        product(captured_at=datetime(2026, 9, 19, 2, tzinfo=timezone.utc)),
        title="新标题",
        price_min=Decimal("45.00"),
        price_max=Decimal("47.00"),
        skus=[
            SkuData("sku-keep", "保留", 8, None),
            SkuData("sku-add", "新增", 2, None),
        ],
    )
    with patch("app.collection.service.collect_1688_product", return_value=current):
        response = client[0].post(f"/api/competitors/{competitor_id}/collect")

    assert response.status_code == 200
    body = response.json()
    assert body["competitor"]["latest_change"]["change_type"] in {
        "price_increase",
        "title_changed",
        "sku_added",
        "sku_removed",
        "stock_changed",
    }
    with client[1]() as session:
        saved_snapshots = session.scalars(
            select(ProductSnapshot)
            .where(ProductSnapshot.competitor_id == competitor_id)
            .order_by(ProductSnapshot.id)
        ).all()
        assert len(saved_snapshots) == 3
        current_snapshot = saved_snapshots[-1]
        assert current_snapshot.id > baseline.id
        events = session.scalars(
            select(ChangeEvent)
            .where(ChangeEvent.competitor_id == competitor_id)
            .order_by(ChangeEvent.id)
        ).all()
        assert [(event.change_type, event.old_value, event.new_value) for event in events] == [
            ("price_increase", "40.00~42.00", "45.00~47.00"),
            ("title_changed", "基线标题", "新标题"),
            ("sku_added", None, "新增"),
            ("sku_removed", "删除", None),
            ("stock_changed", "3", "8"),
        ]
        assert {event.snapshot_id for event in events} == {current_snapshot.id}
        assert {event.competitor_id for event in events} == {competitor_id}
        assert len({event.detected_at for event in events}) == 1
        assert session.scalar(select(CollectionRun).order_by(CollectionRun.id.desc())).status == "success"


@pytest.mark.parametrize(
    ("exception", "code", "status_code"),
    [
        (LoginRequiredError("private"), "1688_login_required", 401),
        (VerificationRequiredError("private"), "1688_verification_required", 403),
        (PageUnavailableError("private"), "1688_page_unavailable", 502),
        (CollectionParseError("private"), "collection_parse_failed", 422),
        (CollectionTimeoutError("private"), "collection_timeout", 504),
        (OfferIdMismatchError("private"), "offer_id_mismatch", 422),
    ],
)
def test_collection_failures_keep_previous_data_and_map_stable_errors(
    client: tuple[TestClient, sessionmaker[Session]],
    exception: Exception,
    code: str,
    status_code: int,
) -> None:
    competitor_id = add_competitor(client[1])
    with patch("app.collection.service.collect_1688_product", side_effect=exception):
        response = client[0].post(f"/api/competitors/{competitor_id}/collect")

    assert response.status_code == status_code
    assert response.json()["code"] == code
    with client[1]() as session:
        saved_competitor = session.get(Competitor, competitor_id)
        assert saved_competitor is not None
        assert saved_competitor.title == "旧标题"
        assert saved_competitor.last_collected_at == datetime(2026, 9, 19)
        assert session.scalar(select(ProductSnapshot)) is None
        run = session.scalar(select(CollectionRun))
        assert run is not None
        assert run.status == "failed"
        assert run.error_type == code
        assert run.error_message != str(exception)


def test_unknown_collection_failure_is_sanitized_and_keeps_previous_snapshot(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    competitor_id = add_competitor(client[1])
    with client[1]() as session:
        session.add(
            ProductSnapshot(
                competitor_id=competitor_id,
                captured_at=datetime(2026, 9, 18, tzinfo=timezone.utc),
                title="旧快照标题",
                shop_name="旧快照店铺",
                main_image_url=None,
                price_min=Decimal("10.00"),
                price_max=Decimal("12.00"),
                product_status="active",
                collection_source="html",
            )
        )
        session.commit()

    raw_error = "raw browser exception with private detail"
    with patch("app.collection.service.collect_1688_product", side_effect=RuntimeError(raw_error)):
        response = client[0].post(f"/api/competitors/{competitor_id}/collect")

    assert response.status_code == 500
    assert response.json() == {
        "code": "collection_failed",
        "message": "采集失败，请稍后重试",
    }
    assert raw_error not in response.text
    with client[1]() as session:
        saved_competitor = session.get(Competitor, competitor_id)
        assert saved_competitor is not None
        assert saved_competitor.title == "旧标题"
        snapshots = session.scalars(select(ProductSnapshot)).all()
        assert len(snapshots) == 1
        assert snapshots[0].title == "旧快照标题"
        run = session.scalar(select(CollectionRun))
        assert run is not None
        assert run.status == "failed"
        assert run.error_type == "collection_failed"
        assert run.error_message == "采集失败，请稍后重试"
        assert raw_error not in run.error_message


def test_nullable_price_and_stock_are_saved_as_null(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    competitor_id = add_competitor(client[1])
    collected = product()
    collected = ProductData(
        **{**collected.__dict__, "price_min": None, "price_max": None}
    )
    with patch("app.collection.service.collect_1688_product", return_value=collected):
        assert client[0].post(f"/api/competitors/{competitor_id}/collect").status_code == 200

    with client[1]() as session:
        snapshot = session.scalar(select(ProductSnapshot))
        assert snapshot is not None
        assert snapshot.price_min is None and snapshot.price_max is None
        saved_skus = session.scalars(select(SkuSnapshot).order_by(SkuSnapshot.id)).all()
        assert saved_skus[0].stock == 3 and saved_skus[0].price is None
        assert saved_skus[1].stock is None and saved_skus[1].price == Decimal("41.00")


def test_save_failure_rolls_back_business_data_and_marks_run_failed(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    competitor_id = add_competitor(client[1])

    def fail_snapshot_insert(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("database failure")

    event.listen(ProductSnapshot, "before_insert", fail_snapshot_insert)
    try:
        with patch("app.collection.service.collect_1688_product", return_value=product()):
            response = client[0].post(f"/api/competitors/{competitor_id}/collect")
    finally:
        event.remove(ProductSnapshot, "before_insert", fail_snapshot_insert)

    assert response.status_code == 500
    assert response.json()["code"] == "collection_save_failed"
    with client[1]() as session:
        saved_competitor = session.get(Competitor, competitor_id)
        assert saved_competitor is not None
        assert saved_competitor.title == "旧标题"
        assert session.scalar(select(ProductSnapshot)) is None
        assert session.scalar(select(SkuSnapshot)) is None
        run = session.scalar(select(CollectionRun))
        assert run is not None
        assert run.status == "failed"
        assert run.error_type == "collection_save_failed"


def test_change_event_save_failure_rolls_back_current_collection(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    competitor_id = add_competitor(client[1])
    first = product(captured_at=datetime(2026, 9, 19, 1, tzinfo=timezone.utc))
    second = replace(
        first,
        title="变化后的标题",
        captured_at=datetime(2026, 9, 19, 2, tzinfo=timezone.utc),
    )
    with patch("app.collection.service.collect_1688_product", return_value=first):
        assert client[0].post(f"/api/competitors/{competitor_id}/collect").status_code == 200

    def fail_change_event_insert(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("change event database failure")

    event.listen(ChangeEvent, "before_insert", fail_change_event_insert)
    try:
        with patch("app.collection.service.collect_1688_product", return_value=second):
            response = client[0].post(f"/api/competitors/{competitor_id}/collect")
    finally:
        event.remove(ChangeEvent, "before_insert", fail_change_event_insert)

    assert response.status_code == 500
    assert response.json() == {"code": "collection_save_failed", "message": "采集结果保存失败"}
    with client[1]() as session:
        assert session.query(ProductSnapshot).count() == 1
        assert session.query(SkuSnapshot).count() == 3
        assert session.query(ChangeEvent).count() == 0
        saved_snapshot = session.scalar(select(ProductSnapshot))
        assert saved_snapshot is not None
        assert saved_snapshot.title == "新商品标题"
        saved_competitor = session.get(Competitor, competitor_id)
        assert saved_competitor is not None
        assert saved_competitor.title == "新商品标题"
        runs = session.scalars(select(CollectionRun).order_by(CollectionRun.id)).all()
        assert len(runs) == 2
        assert runs[-1].status == "failed"
        assert runs[-1].error_type == "collection_save_failed"


def test_listing_without_snapshot_returns_null_projection(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    add_competitor(client[1])
    body = client[0].get("/api/competitors").json()

    assert body[0]["latest_snapshot"] is None
