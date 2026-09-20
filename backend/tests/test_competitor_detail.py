from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

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


def test_missing_competitor_returns_stable_detail_error(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    response = client[0].get("/api/competitors/999/detail")

    assert response.status_code == 404
    assert response.json() == {"code": "competitor_not_found", "message": "竞品不存在"}


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


def add_snapshot(
    session: Session,
    competitor_id: int,
    captured_at: datetime,
    *,
    price_min: Decimal | None = Decimal("40.00"),
    price_max: Decimal | None = Decimal("45.00"),
    sku_id: str | None = None,
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
    if sku_id is not None:
        snapshot.skus = [
            SkuSnapshot(sku_id=sku_id, sku_name=sku_id, stock=0, price=None),
            SkuSnapshot(sku_id="sku-null", sku_name="无库存", stock=None, price=Decimal("41.00")),
        ]
    session.add(snapshot)
    session.flush()
    return snapshot


def test_no_snapshot_returns_empty_detail_sections(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    with client[1]() as session:
        competitor = add_competitor(session)
        session.commit()

    body = client[0].get(f"/api/competitors/{competitor.id}/detail").json()

    assert body["range_days"] == 7
    assert body["latest_snapshot"] is None
    assert body["latest_skus"] == []
    assert body["price_trend"] == []


def test_latest_snapshot_and_skus_use_captured_at_then_id_and_preserve_nulls(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    captured_at = datetime.now(timezone.utc) - timedelta(days=20)
    with client[1]() as session:
        competitor = add_competitor(session)
        older = add_snapshot(session, competitor.id, captured_at, sku_id="old-sku")
        first = add_snapshot(session, competitor.id, captured_at, sku_id="first-sku")
        latest = add_snapshot(
            session,
            competitor.id,
            captured_at,
            price_min=None,
            price_max=None,
            sku_id="latest-sku",
        )
        session.commit()

    body = client[0].get(f"/api/competitors/{competitor.id}/detail?days=7").json()

    assert body["latest_snapshot"]["id"] == latest.id
    assert body["latest_snapshot"]["sku_count"] == 2
    assert body["latest_snapshot"]["price_min"] is None
    assert [sku["sku_id"] for sku in body["latest_skus"]] == ["latest-sku", "sku-null"]
    assert body["latest_skus"][0]["stock"] == 0
    assert body["latest_skus"][1]["stock"] is None
    assert body["latest_skus"][1]["price"] == "41.00"
    assert body["price_trend"] == []
    assert older.id < first.id < latest.id


def test_price_trend_uses_utc_window_and_captured_at_id_ascending_order(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    now = datetime.now(timezone.utc)
    with client[1]() as session:
        competitor = add_competitor(session)
        old = add_snapshot(session, competitor.id, now - timedelta(days=8))
        in_seven_days = add_snapshot(session, competitor.id, now - timedelta(days=3))
        same_time_first = add_snapshot(session, competitor.id, now - timedelta(days=1))
        same_time_second = add_snapshot(session, competitor.id, now - timedelta(days=1))
        in_thirty_days = add_snapshot(session, competitor.id, now - timedelta(days=20))
        session.commit()

    seven = client[0].get(f"/api/competitors/{competitor.id}/detail?days=7").json()["price_trend"]
    thirty = client[0].get(f"/api/competitors/{competitor.id}/detail?days=30").json()["price_trend"]

    assert old.id not in [item["snapshot_id"] for item in seven]
    assert [item["snapshot_id"] for item in seven] == [in_seven_days.id, same_time_first.id, same_time_second.id]
    assert [item["snapshot_id"] for item in thirty] == [in_thirty_days.id, old.id, in_seven_days.id, same_time_first.id, same_time_second.id]


def test_price_trend_keeps_null_prices(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    with client[1]() as session:
        competitor = add_competitor(session)
        snapshot = add_snapshot(
            session,
            competitor.id,
            datetime.now(timezone.utc) - timedelta(hours=1),
            price_min=None,
            price_max=None,
        )
        session.commit()

    trend = client[0].get(f"/api/competitors/{competitor.id}/detail").json()["price_trend"]

    assert trend == [{
        "snapshot_id": snapshot.id,
        "captured_at": snapshot.captured_at.replace(tzinfo=None).isoformat(),
        "price_min": None,
        "price_max": None,
    }]


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
                change_type="title_changed",
                detected_at=timestamp,
            )
            for _ in range(21)
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

    body = client[0].get(f"/api/competitors/{competitor.id}/detail").json()

    assert len(body["recent_changes"]) == 20
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
