from collections.abc import Generator
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.competitor_groups as competitor_groups_module
from app.database import get_db
from app.main import app
from app.models import (
    Base,
    ChangeEvent,
    CollectionRun,
    Competitor,
    CompetitorGroup,
    ProductSnapshot,
    SkuSnapshot,
)


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


def test_creates_group_with_trimmed_name(client: tuple[TestClient, sessionmaker[Session]]) -> None:
    response = client[0].post("/api/competitor-groups", json={"name": "  暖手宝  "})

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "暖手宝"
    assert set(body) == {"id", "name", "created_at"}


@pytest.mark.parametrize("name", ["", "   ", "a" * 65])
def test_rejects_invalid_group_name(
    client: tuple[TestClient, sessionmaker[Session]], name: str
) -> None:
    response = client[0].post("/api/competitor-groups", json={"name": name})

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_competitor_group_name"


def test_duplicate_group_name_returns_conflict(client: tuple[TestClient, sessionmaker[Session]]) -> None:
    test_client = client[0]
    assert test_client.post("/api/competitor-groups", json={"name": "暖手宝"}).status_code == 201

    response = test_client.post("/api/competitor-groups", json={"name": "  暖手宝 "})

    assert response.status_code == 409
    assert response.json()["code"] == "competitor_group_already_exists"


def test_group_name_unique_constraint_is_enforced_by_database(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    with client[1]() as session:
        now = datetime.now(timezone.utc)
        session.add(CompetitorGroup(name="暖手宝", created_at=now))
        session.commit()
        session.add(CompetitorGroup(name="暖手宝", created_at=now))
        with pytest.raises(IntegrityError):
            session.commit()


def test_lists_groups_in_created_at_and_id_ascending_order(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    timestamp = datetime(2026, 9, 20, 10, tzinfo=timezone.utc)
    with client[1]() as session:
        session.add_all(
            [
                CompetitorGroup(name="第二组", created_at=timestamp),
                CompetitorGroup(name="第一组", created_at=timestamp),
            ]
        )
        session.commit()
        expected_names = [group.name for group in session.scalars(
            select(CompetitorGroup).order_by(CompetitorGroup.created_at, CompetitorGroup.id)
        ).all()]

    response = client[0].get("/api/competitor-groups")

    assert response.status_code == 200
    assert [item["name"] for item in response.json()] == expected_names


def test_competitor_group_foreign_key_is_enforced(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    with client[1]() as session:
        session.add(
            Competitor(
                group_id=999,
                platform="1688",
                offer_id="123456789",
                url="https://detail.1688.com/offer/123456789.html",
                status="unknown",
                is_active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def _add_competitor(
    session: Session,
    competitor_id: int,
    *,
    group_id: int | None,
    is_active: bool = True,
) -> Competitor:
    competitor = Competitor(
        id=competitor_id,
        group_id=group_id,
        platform="1688",
        offer_id=str(competitor_id),
        url=f"https://detail.1688.com/offer/{competitor_id}.html",
        status="unknown",
        is_active=is_active,
        created_at=datetime(2026, 9, 19, tzinfo=timezone.utc),
        updated_at=datetime(2026, 9, 19, tzinfo=timezone.utc),
    )
    session.add(competitor)
    return competitor


def _add_snapshot(
    session: Session,
    competitor_id: int,
    snapshot_id: int,
    captured_at: datetime,
    *,
    price_min: Decimal | None,
    price_max: Decimal | None,
) -> ProductSnapshot:
    snapshot = ProductSnapshot(
        id=snapshot_id,
        competitor_id=competitor_id,
        captured_at=captured_at,
        title=f"商品 {competitor_id}",
        shop_name="测试店铺",
        price_min=price_min,
        price_max=price_max,
        product_status="active",
        collection_source="html",
    )
    session.add(snapshot)
    return snapshot


def _add_change(
    session: Session,
    competitor_id: int,
    snapshot_id: int,
    change_id: int,
    detected_at: datetime,
) -> ChangeEvent:
    event = ChangeEvent(
        id=change_id,
        competitor_id=competitor_id,
        snapshot_id=snapshot_id,
        change_type="title_changed",
        detected_at=detected_at,
    )
    session.add(event)
    return event


def test_summary_returns_group_and_unassigned_metrics_without_mixing_history(
    client: tuple[TestClient, sessionmaker[Session]], monkeypatch: pytest.MonkeyPatch
) -> None:
    business_start = datetime(2026, 9, 20, 16)
    business_end = datetime(2026, 9, 21, 16)
    monkeypatch.setattr(
        competitor_groups_module,
        "business_day_bounds",
        lambda: (datetime(2026, 9, 21).date(), business_start, business_end),
    )
    with client[1]() as session:
        group = CompetitorGroup(id=1, name="A19", created_at=datetime(2026, 9, 19))
        empty_group = CompetitorGroup(id=2, name="X6", created_at=datetime(2026, 9, 20))
        session.add_all([group, empty_group])
        session.flush()
        _add_competitor(session, 1, group_id=1, is_active=True)
        _add_competitor(session, 2, group_id=1, is_active=False)
        _add_competitor(session, 3, group_id=1, is_active=True)
        _add_competitor(session, 4, group_id=None, is_active=True)
        _add_snapshot(session, 1, 11, datetime(2026, 9, 19, 1), price_min=Decimal("10"), price_max=Decimal("12"))
        _add_snapshot(session, 1, 12, datetime(2026, 9, 20, 1), price_min=Decimal("20"), price_max=None)
        _add_snapshot(session, 2, 21, datetime(2026, 9, 20, 2), price_min=None, price_max=Decimal("30"))
        _add_snapshot(session, 3, 31, datetime(2026, 9, 20, 3), price_min=None, price_max=None)
        _add_snapshot(session, 4, 41, datetime(2026, 9, 20, 4), price_min=Decimal("40"), price_max=Decimal("45"))
        session.flush()
        _add_change(session, 2, 21, 201, datetime(2026, 9, 21, 8))
        _add_change(session, 2, 21, 202, datetime(2026, 9, 21, 9))
        _add_change(session, 2, 21, 203, datetime(2026, 9, 20, 15))
        _add_change(session, 4, 41, 401, datetime(2026, 9, 21, 10))
        session.commit()

    response = client[0].get("/api/competitor-groups/summary")

    assert response.status_code == 200
    body = response.json()
    assert [item["name"] for item in body["groups"]] == ["A19", "X6"]
    assert body["groups"][0] == {
        "id": 1,
        "name": "A19",
        "created_at": "2026-09-19T00:00:00",
        "competitor_count": 3,
        "active_count": 2,
        "price_min": "20.00",
        "price_max": "30.00",
        "changed_competitors_today": 1,
        "last_change_at": "2026-09-21T09:00:00",
    }
    assert body["groups"][1]["competitor_count"] == 0
    assert body["groups"][1]["price_min"] is None
    assert body["groups"][1]["price_max"] is None
    assert body["groups"][1]["last_change_at"] is None
    assert body["unassigned"] == {
        "competitor_count": 1,
        "active_count": 1,
        "price_min": "40.00",
        "price_max": "45.00",
        "changed_competitors_today": 1,
        "last_change_at": "2026-09-21T10:00:00",
    }


def test_summary_uses_last_change_sorting_and_stable_ties(
    client: tuple[TestClient, sessionmaker[Session]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        competitor_groups_module,
        "business_day_bounds",
        lambda: (datetime(2026, 9, 21).date(), datetime(2026, 9, 20), datetime(2026, 9, 21)),
    )
    with client[1]() as session:
        session.add_all(
            [
                CompetitorGroup(id=1, name="无变化", created_at=datetime(2026, 9, 19)),
                CompetitorGroup(id=2, name="较新变化", created_at=datetime(2026, 9, 20)),
                CompetitorGroup(id=3, name="较旧变化", created_at=datetime(2026, 9, 18)),
            ]
        )
        session.flush()
        _add_competitor(session, 2, group_id=2)
        _add_competitor(session, 3, group_id=3)
        _add_snapshot(session, 2, 22, datetime(2026, 9, 20, 1), price_min=None, price_max=None)
        _add_snapshot(session, 3, 33, datetime(2026, 9, 20, 1), price_min=None, price_max=None)
        session.flush()
        _add_change(session, 2, 22, 2, datetime(2026, 9, 20, 8))
        _add_change(session, 3, 33, 3, datetime(2026, 9, 20, 7))
        session.commit()

    response = client[0].get("/api/competitor-groups/summary")

    assert [item["name"] for item in response.json()["groups"]] == ["较新变化", "较旧变化", "无变化"]


def test_summary_returns_empty_groups_and_unassigned_when_no_competitors(
    client: tuple[TestClient, sessionmaker[Session]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        competitor_groups_module,
        "business_day_bounds",
        lambda: (datetime(2026, 9, 21).date(), datetime(2026, 9, 20), datetime(2026, 9, 21)),
    )

    response = client[0].get("/api/competitor-groups/summary")

    assert response.status_code == 200
    assert response.json() == {
        "groups": [],
        "unassigned": {
            "competitor_count": 0,
            "active_count": 0,
            "price_min": None,
            "price_max": None,
            "changed_competitors_today": 0,
            "last_change_at": None,
        },
    }


def test_summary_uses_one_valid_price_as_both_bounds(
    client: tuple[TestClient, sessionmaker[Session]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        competitor_groups_module,
        "business_day_bounds",
        lambda: (datetime(2026, 9, 21).date(), datetime(2026, 9, 20), datetime(2026, 9, 21)),
    )
    with client[1]() as session:
        session.add(CompetitorGroup(id=1, name="A19", created_at=datetime(2026, 9, 19)))
        session.flush()
        _add_competitor(session, 1, group_id=1)
        _add_snapshot(session, 1, 11, datetime(2026, 9, 20), price_min=Decimal("39"), price_max=None)
        session.commit()

    response = client[0].get("/api/competitor-groups/summary")

    assert response.json()["groups"][0]["price_min"] == "39.00"
    assert response.json()["groups"][0]["price_max"] == "39.00"


def test_renames_group_without_changing_competitor_relationship(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    with client[1]() as session:
        session.add(CompetitorGroup(id=1, name="A19", created_at=datetime(2026, 9, 19)))
        session.flush()
        _add_competitor(session, 1, group_id=1)
        session.commit()

    response = client[0].patch("/api/competitor-groups/1", json={"name": " A19 Pro "})

    assert response.status_code == 200
    assert response.json()["name"] == "A19 Pro"
    with client[1]() as session:
        assert session.get(Competitor, 1).group_id == 1


@pytest.mark.parametrize(
    ("method", "payload", "code"),
    [
        ("patch", {"name": "  "}, "invalid_competitor_group_name"),
        ("patch", {"name": "A" * 65}, "invalid_competitor_group_name"),
    ],
)
def test_rename_rejects_invalid_name(
    client: tuple[TestClient, sessionmaker[Session]], method: str, payload: dict[str, str], code: str
) -> None:
    client[0].post("/api/competitor-groups", json={"name": "A19"})

    response = client[0].patch("/api/competitor-groups/1", json=payload)

    assert response.status_code == 400
    assert response.json()["code"] == code


def test_rename_returns_not_found_and_duplicate_errors(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client = client[0]
    test_client.post("/api/competitor-groups", json={"name": "A19"})
    test_client.post("/api/competitor-groups", json={"name": "X6"})

    missing = test_client.patch("/api/competitor-groups/99", json={"name": "N09A"})
    duplicate = test_client.patch("/api/competitor-groups/2", json={"name": " A19 "})

    assert missing.status_code == 404
    assert missing.json()["code"] == "competitor_group_not_found"
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "competitor_group_already_exists"


def test_deletes_group_by_unassigning_competitors_and_preserving_history(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    with client[1]() as session:
        session.add(CompetitorGroup(id=1, name="A19", created_at=datetime(2026, 9, 19)))
        session.flush()
        competitor = _add_competitor(session, 1, group_id=1, is_active=False)
        session.flush()
        snapshot = _add_snapshot(session, 1, 11, datetime(2026, 9, 20), price_min=Decimal("39"), price_max=None)
        session.flush()
        session.add(SkuSnapshot(product_snapshot_id=snapshot.id, sku_id="sku-1", sku_name="红色", stock=None, price=None))
        session.add(ChangeEvent(id=101, competitor_id=competitor.id, snapshot_id=snapshot.id, change_type="title_changed", detected_at=datetime(2026, 9, 20)))
        session.add(CollectionRun(id=201, competitor_id=competitor.id, started_at=datetime(2026, 9, 20), status="success"))
        session.commit()

    response = client[0].delete("/api/competitor-groups/1")

    assert response.status_code == 204
    with client[1]() as session:
        assert session.get(CompetitorGroup, 1) is None
        preserved = session.get(Competitor, 1)
        assert preserved is not None
        assert preserved.group_id is None
        assert preserved.is_active is False
        assert session.scalar(select(ProductSnapshot).where(ProductSnapshot.id == 11)) is not None
        assert session.scalar(select(SkuSnapshot).where(SkuSnapshot.product_snapshot_id == 11)) is not None
        assert session.scalar(select(ChangeEvent).where(ChangeEvent.id == 101)) is not None
        assert session.scalar(select(CollectionRun).where(CollectionRun.id == 201)) is not None


def test_deletes_empty_group_and_returns_not_found_for_missing_group(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client[0].post("/api/competitor-groups", json={"name": "A19"})

    deleted = client[0].delete("/api/competitor-groups/1")
    missing = client[0].delete("/api/competitor-groups/1")

    assert deleted.status_code == 204
    assert missing.status_code == 404
    assert missing.json()["code"] == "competitor_group_not_found"


def test_delete_rolls_back_when_unassigning_fails(
    client: tuple[TestClient, sessionmaker[Session]], monkeypatch: pytest.MonkeyPatch
) -> None:
    with client[1]() as session:
        session.add(CompetitorGroup(id=1, name="A19", created_at=datetime(2026, 9, 19)))
        session.flush()
        _add_competitor(session, 1, group_id=1)
        session.commit()

    def fail_update(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("forced failure")

    monkeypatch.setattr(competitor_groups_module, "update", fail_update)
    response = client[0].delete("/api/competitor-groups/1")

    assert response.status_code == 500
    assert response.json()["code"] == "competitor_group_delete_failed"
    with client[1]() as session:
        assert session.get(CompetitorGroup, 1) is not None
        assert session.get(Competitor, 1).group_id == 1
