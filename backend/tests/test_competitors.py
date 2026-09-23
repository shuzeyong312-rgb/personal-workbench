from collections.abc import Generator
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import app
from app.collection.service import COLLECTION_LOCK
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


def test_adds_competitor_and_normalizes_url(client: tuple[TestClient, sessionmaker[Session]]) -> None:
    test_client, session_factory = client

    response = test_client.post(
        "/api/competitors",
        json={"url": "https://detail.1688.com/offer/123456789.html?spm=abc#top"},
    )

    assert response.status_code == 201
    assert response.json()["platform"] == "1688"
    assert response.json()["offer_id"] == "123456789"
    assert response.json()["url"] == "https://detail.1688.com/offer/123456789.html"
    assert response.json()["group_id"] is None
    assert response.json()["group_role"] == "competitor"
    assert response.json()["status"] == "unknown"
    assert response.json()["is_active"] is True

    with session_factory() as session:
        competitors = session.scalars(select(Competitor)).all()
        assert len(competitors) == 1
        assert competitors[0].offer_id == "123456789"


def test_lists_empty_competitors(client: tuple[TestClient, sessionmaker[Session]]) -> None:
    response = client[0].get("/api/competitors")

    assert response.status_code == 200
    assert response.json() == []


def test_lists_all_competitors_in_created_at_and_id_desc_order(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    with session_factory() as session:
        session.add_all(
            [
                Competitor(
                    platform="1688",
                    offer_id="111",
                    url="https://detail.1688.com/offer/111.html",
                    title="older",
                    status="unknown",
                    is_active=True,
                    created_at=datetime(2026, 9, 18, tzinfo=timezone.utc),
                    updated_at=datetime(2026, 9, 18, tzinfo=timezone.utc),
                ),
                Competitor(
                    platform="1688",
                    offer_id="222",
                    url="https://detail.1688.com/offer/222.html",
                    title="newer low id",
                    status="active",
                    is_active=True,
                    created_at=datetime(2026, 9, 19, tzinfo=timezone.utc),
                    updated_at=datetime(2026, 9, 19, tzinfo=timezone.utc),
                ),
                Competitor(
                    platform="1688",
                    offer_id="333",
                    url="https://detail.1688.com/offer/333.html",
                    status="offline",
                    is_active=False,
                    created_at=datetime(2026, 9, 19, tzinfo=timezone.utc),
                    updated_at=datetime(2026, 9, 19, tzinfo=timezone.utc),
                ),
            ]
        )
        session.commit()

    response = test_client.get("/api/competitors")

    assert response.status_code == 200
    body = response.json()
    assert [item["offer_id"] for item in body] == ["333", "222", "111"]
    assert set(body[0]) == {
        "id",
        "platform",
        "offer_id",
        "url",
        "group_id",
        "group_role",
        "group_role",
        "title",
        "shop_name",
        "main_image_url",
        "status",
        "is_active",
        "created_at",
        "last_collected_at",
        "latest_snapshot",
        "latest_change",
    }
    assert body[0]["latest_change"] is None


def test_listing_returns_latest_real_change_per_competitor_with_id_tiebreak(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    detected_at = datetime(2026, 9, 19, 12, tzinfo=timezone.utc)
    with session_factory() as session:
        first = Competitor(
            platform="1688",
            offer_id="111",
            url="https://detail.1688.com/offer/111.html",
            status="active",
            is_active=True,
            created_at=detected_at,
            updated_at=detected_at,
        )
        second = Competitor(
            platform="1688",
            offer_id="222",
            url="https://detail.1688.com/offer/222.html",
            status="active",
            is_active=True,
            created_at=detected_at,
            updated_at=detected_at,
        )
        session.add_all([first, second])
        session.flush()
        snapshots = [
            ProductSnapshot(
                competitor_id=first.id,
                captured_at=detected_at,
                title="一",
                shop_name="店",
                product_status="active",
                collection_source="html",
            ),
            ProductSnapshot(
                competitor_id=first.id,
                captured_at=detected_at,
                title="二",
                shop_name="店",
                product_status="active",
                collection_source="html",
            ),
            ProductSnapshot(
                competitor_id=second.id,
                captured_at=detected_at,
                title="三",
                shop_name="店",
                product_status="active",
                collection_source="html",
            ),
        ]
        session.add_all(snapshots)
        session.flush()
        session.add(
            ChangeEvent(
                competitor_id=first.id,
                snapshot_id=snapshots[0].id,
                change_type="title_changed",
                old_value="一",
                new_value="二",
                detected_at=detected_at,
            )
        )
        session.flush()
        newest_first_event = ChangeEvent(
            competitor_id=first.id,
            snapshot_id=snapshots[1].id,
            change_type="price_increase",
            old_value="1.00",
            new_value="2.00",
            detected_at=detected_at,
        )
        session.add_all(
            [
                newest_first_event,
                ChangeEvent(
                    competitor_id=second.id,
                    snapshot_id=snapshots[2].id,
                    change_type="sku_added",
                    entity_key="sku-2",
                    new_value="蓝色",
                    detected_at=detected_at,
                ),
            ]
        )
        session.commit()

    body = {item["offer_id"]: item for item in test_client.get("/api/competitors").json()}
    first_change = body["111"]["latest_change"]
    assert first_change == {
            "id": newest_first_event.id,
            "snapshot_id": snapshots[1].id,
            "collection_run_id": None,
            "change_type": "price_increase",
        "entity_key": None,
        "sku_name": None,
        "old_value": "1.00",
            "new_value": "2.00",
            "delta_value": None,
            "delta_rate": None,
            "detected_at": "2026-09-19T12:00:00",
    }
    assert body["222"]["latest_change"]["change_type"] == "sku_added"
    assert "changes" not in body["111"]


def test_listing_does_not_trigger_collection_side_effects(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    response = client[0].get("/api/competitors")

    assert response.status_code == 200
    with client[1]() as session:
        assert session.query(Competitor).count() == 0


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://detail.1688.com/offer/123456789.html",
        "https://m.1688.com/offer/123456789.html",
        "https://detail.1688.com/page/123456789.html",
        "https://detail.1688.com/offer/not-numeric.html",
        "https://user:pass@detail.1688.com/offer/123456789.html",
        "https://detail.1688.com:8443/offer/123456789.html",
    ],
)
def test_rejects_invalid_1688_url(
    client: tuple[TestClient, sessionmaker[Session]], url: str
) -> None:
    response = client[0].post("/api/competitors", json={"url": url})

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_competitor_url"


def test_adds_competitor_to_existing_group(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    group_response = client[0].post("/api/competitor-groups", json={"name": "暖手宝"})
    group_id = group_response.json()["id"]

    response = client[0].post(
        "/api/competitors",
        json={"url": "https://detail.1688.com/offer/123456789.html", "group_id": group_id},
    )

    assert response.status_code == 201
    assert response.json()["group_id"] == group_id


def test_nonexistent_group_id_returns_not_found(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    response = client[0].post(
        "/api/competitors",
        json={"url": "https://detail.1688.com/offer/123456789.html", "group_id": 999},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "competitor_group_not_found"


def test_list_returns_competitor_group_id(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    group_id = client[0].post("/api/competitor-groups", json={"name": "暖手宝"}).json()["id"]
    client[0].post(
        "/api/competitors",
        json={"url": "https://detail.1688.com/offer/123456789.html", "group_id": group_id},
    )

    assert client[0].get("/api/competitors").json()[0]["group_id"] == group_id


def test_updates_competitor_group_assignment_and_preserves_history(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    first_group_id = test_client.post("/api/competitor-groups", json={"name": "A19"}).json()["id"]
    second_group_id = test_client.post("/api/competitor-groups", json={"name": "X6"}).json()["id"]
    competitor_id = test_client.post(
        "/api/competitors",
        json={"url": "https://detail.1688.com/offer/123456789.html", "group_id": first_group_id},
    ).json()["id"]
    assert test_client.put(
        f"/api/competitor-groups/{first_group_id}/own-product",
        json={"competitor_id": competitor_id},
    ).status_code == 200
    now = datetime(2026, 9, 20, tzinfo=timezone.utc)
    with session_factory() as session:
        snapshot = ProductSnapshot(
            competitor_id=competitor_id,
            captured_at=now,
            title="历史商品",
            shop_name="历史店铺",
            product_status="active",
            collection_source="html",
            skus=[SkuSnapshot(sku_id="sku-1", sku_name="红色", stock=2, price=None)],
        )
        session.add(snapshot)
        session.flush()
        session.add_all(
            [
                ChangeEvent(
                    competitor_id=competitor_id,
                    snapshot_id=snapshot.id,
                    change_type="title_changed",
                    old_value="旧标题",
                    new_value="历史商品",
                    detected_at=now,
                ),
                CollectionRun(
                    competitor_id=competitor_id,
                    started_at=now,
                    finished_at=now,
                    status="success",
                ),
            ]
        )
        session.commit()

    moved = test_client.patch(f"/api/competitors/{competitor_id}/group", json={"group_id": second_group_id})
    assert moved.status_code == 200
    assert moved.json()["group_id"] == second_group_id
    assert moved.json()["group_role"] == "competitor"
    assert moved.json()["is_active"] is True

    unassigned = test_client.patch(f"/api/competitors/{competitor_id}/group", json={"group_id": None})
    assert unassigned.status_code == 200
    assert unassigned.json()["group_id"] is None
    assert unassigned.json()["group_role"] == "competitor"

    reassigned = test_client.patch(f"/api/competitors/{competitor_id}/group", json={"group_id": first_group_id})
    assert reassigned.status_code == 200
    assert reassigned.json()["group_id"] == first_group_id

    idempotent = test_client.patch(f"/api/competitors/{competitor_id}/group", json={"group_id": first_group_id})
    assert idempotent.status_code == 200
    assert idempotent.json()["group_id"] == first_group_id

    with session_factory() as session:
        assert session.scalar(select(ProductSnapshot)) is not None
        assert session.scalar(select(SkuSnapshot)) is not None
        assert session.scalar(select(ChangeEvent)) is not None
        assert session.scalar(select(CollectionRun)) is not None


def test_group_assignment_rejects_missing_competitor_and_group(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client = client[0]
    missing_competitor = test_client.patch("/api/competitors/999/group", json={"group_id": None})
    assert missing_competitor.status_code == 404
    assert missing_competitor.json()["code"] == "competitor_not_found"

    competitor_id = test_client.post(
        "/api/competitors", json={"url": "https://detail.1688.com/offer/123456789.html"}
    ).json()["id"]
    missing_group = test_client.patch(f"/api/competitors/{competitor_id}/group", json={"group_id": 999})
    assert missing_group.status_code == 404
    assert missing_group.json()["code"] == "competitor_group_not_found"


def test_assignment_demotes_own_without_replacing_destination_own(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client = client[0]
    group_a = test_client.post("/api/competitor-groups", json={"name": "A19"}).json()["id"]
    group_b = test_client.post("/api/competitor-groups", json={"name": "X6"}).json()["id"]
    ids = [
        test_client.post("/api/competitors", json={"url": f"https://detail.1688.com/offer/{offer}.html", "group_id": group_id}).json()["id"]
        for offer, group_id in (("101", group_a), ("102", group_b))
    ]
    assert test_client.put(f"/api/competitor-groups/{group_a}/own-product", json={"competitor_id": ids[0]}).status_code == 200
    assert test_client.put(f"/api/competitor-groups/{group_b}/own-product", json={"competitor_id": ids[1]}).status_code == 200

    moved = test_client.patch(f"/api/competitors/{ids[0]}/group", json={"group_id": group_b})
    assert moved.status_code == 200
    assert moved.json()["group_role"] == "competitor"
    assert test_client.patch(f"/api/competitors/{ids[0]}/group", json={"group_id": None}).json()["group_role"] == "competitor"
    with client[1]() as session:
        assert session.get(Competitor, ids[1]).group_role == "own"
        assert session.get(Competitor, ids[0]).group_id is None


def test_duplicate_offer_id_returns_409_without_new_record(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    url = "https://detail.1688.com/offer/123456789.html"

    assert test_client.post("/api/competitors", json={"url": url}).status_code == 201
    response = test_client.post(
        "/api/competitors",
        json={"url": f"{url}?spm=another"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "competitor_already_exists"
    with session_factory() as session:
        assert len(session.scalars(select(Competitor)).all()) == 1


def test_status_constraint_rejects_unknown_value(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    _, session_factory = client
    with session_factory() as session:
        session.add(
            Competitor(
                platform="1688",
                offer_id="987654321",
                url="https://detail.1688.com/offer/987654321.html",
                status="invalid",
                is_active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_monitoring_lifecycle_preserves_history_and_supports_resume(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    competitor_id = test_client.post(
        "/api/competitors", json={"url": "https://detail.1688.com/offer/123456789.html"}
    ).json()["id"]
    now = datetime(2026, 9, 20, tzinfo=timezone.utc)
    with session_factory() as session:
        snapshot = ProductSnapshot(
            competitor_id=competitor_id,
            captured_at=now,
            title="历史商品",
            shop_name="历史店铺",
            price_min=Decimal("10.00"),
            price_max=Decimal("12.00"),
            product_status="active",
            collection_source="html",
            skus=[SkuSnapshot(sku_id="sku-1", sku_name="红色", stock=2, price=None)],
        )
        session.add(snapshot)
        session.flush()
        session.add(
            ChangeEvent(
                competitor_id=competitor_id,
                snapshot_id=snapshot.id,
                change_type="title_changed",
                old_value="旧标题",
                new_value="历史商品",
                detected_at=now,
            )
        )
        session.add(
            CollectionRun(
                competitor_id=competitor_id,
                started_at=now,
                finished_at=now,
                status="success",
            )
        )
        session.commit()

    stopped = test_client.patch(
        f"/api/competitors/{competitor_id}/monitoring", json={"is_active": False}
    )
    assert stopped.status_code == 200
    assert stopped.json()["is_active"] is False
    with session_factory() as session:
        assert session.scalar(select(ProductSnapshot)) is not None
        assert session.scalar(select(SkuSnapshot)) is not None
        assert session.scalar(select(ChangeEvent)) is not None
        assert session.scalar(select(CollectionRun)) is not None

    resumed = test_client.patch(
        f"/api/competitors/{competitor_id}/monitoring", json={"is_active": True}
    )
    assert resumed.status_code == 200
    assert resumed.json()["is_active"] is True


def test_inactive_competitor_cannot_be_collected(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    competitor_id = test_client.post(
        "/api/competitors", json={"url": "https://detail.1688.com/offer/123456789.html"}
    ).json()["id"]
    with session_factory() as session:
        competitor = session.get(Competitor, competitor_id)
        assert competitor is not None
        competitor.is_active = False
        session.commit()

    with patch("app.collection.service.collect_1688_product") as collector:
        response = test_client.post(f"/api/competitors/{competitor_id}/collect")

    assert response.status_code == 409
    assert response.json() == {
        "code": "competitor_inactive",
        "message": "该竞品已停止监控，无法立即采集",
    }
    collector.assert_not_called()
    with session_factory() as session:
        assert session.scalar(select(CollectionRun)) is None


def test_delete_uncollected_competitor_and_allow_readding_same_offer(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    url = "https://detail.1688.com/offer/123456789.html"
    competitor_id = test_client.post("/api/competitors", json={"url": url}).json()["id"]

    response = test_client.delete(f"/api/competitors/{competitor_id}")

    assert response.status_code == 204
    with session_factory() as session:
        assert session.scalar(select(Competitor)) is None
    assert test_client.post("/api/competitors", json={"url": url}).status_code == 201


def test_delete_removes_all_competitor_history_but_not_group(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    group_id = test_client.post("/api/competitor-groups", json={"name": "保留分组"}).json()["id"]
    competitor_id = test_client.post(
        "/api/competitors",
        json={"url": "https://detail.1688.com/offer/123456789.html", "group_id": group_id},
    ).json()["id"]
    now = datetime(2026, 9, 20, tzinfo=timezone.utc)
    with session_factory() as session:
        snapshot = ProductSnapshot(
            competitor_id=competitor_id,
            captured_at=now,
            title="历史商品",
            shop_name="历史店铺",
            product_status="unknown",
            collection_source="html",
            skus=[SkuSnapshot(sku_id="sku-1", sku_name="红色", stock=0, price=None)],
        )
        session.add(snapshot)
        session.flush()
        session.add_all(
            [
                ChangeEvent(
                    competitor_id=competitor_id,
                    snapshot_id=snapshot.id,
                    change_type="title_changed",
                    detected_at=now,
                ),
                CollectionRun(
                    competitor_id=competitor_id,
                    started_at=now,
                    finished_at=now,
                    status="success",
                ),
            ]
        )
        session.commit()

    response = test_client.delete(f"/api/competitors/{competitor_id}")

    assert response.status_code == 204
    with session_factory() as session:
        assert session.scalar(select(Competitor)) is None
        assert session.scalar(select(ProductSnapshot)) is None
        assert session.scalar(select(SkuSnapshot)) is None
        assert session.scalar(select(ChangeEvent)) is None
        assert session.scalar(select(CollectionRun)) is None
        assert session.get(CompetitorGroup, group_id) is not None
    assert test_client.get("/api/competitor-groups/summary").json()["groups"][0]["own_product"] is None


def test_delete_missing_competitor_returns_stable_404(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    response = client[0].delete("/api/competitors/999")

    assert response.status_code == 404
    assert response.json() == {"code": "competitor_not_found", "message": "竞品不存在"}


def test_delete_during_collection_returns_conflict(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    competitor_id = test_client.post(
        "/api/competitors", json={"url": "https://detail.1688.com/offer/123456789.html"}
    ).json()["id"]
    COLLECTION_LOCK.acquire()
    try:
        response = test_client.delete(f"/api/competitors/{competitor_id}")
    finally:
        COLLECTION_LOCK.release()

    assert response.status_code == 409
    assert response.json()["code"] == "collection_in_progress"
    with session_factory() as session:
        assert session.get(Competitor, competitor_id) is not None


def test_delete_rolls_back_when_history_delete_fails(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    competitor_id = test_client.post(
        "/api/competitors", json={"url": "https://detail.1688.com/offer/123456789.html"}
    ).json()["id"]
    now = datetime(2026, 9, 20, tzinfo=timezone.utc)
    with session_factory() as session:
        snapshot = ProductSnapshot(
            competitor_id=competitor_id,
            captured_at=now,
            title="历史商品",
            shop_name="历史店铺",
            product_status="unknown",
            collection_source="html",
        )
        session.add(snapshot)
        session.flush()
        session.add(
            ChangeEvent(
                competitor_id=competitor_id,
                snapshot_id=snapshot.id,
                change_type="title_changed",
                detected_at=now,
            )
        )
        session.commit()

    with patch.object(Session, "commit", side_effect=RuntimeError("commit failed")):
        response = test_client.delete(f"/api/competitors/{competitor_id}")

    assert response.status_code == 500
    assert response.json() == {
        "code": "competitor_delete_failed",
        "message": "竞品删除失败，请稍后重试",
    }
    with session_factory() as session:
        assert session.get(Competitor, competitor_id) is not None
        assert session.scalar(select(ProductSnapshot)) is not None
        assert session.scalar(select(ChangeEvent)) is not None
