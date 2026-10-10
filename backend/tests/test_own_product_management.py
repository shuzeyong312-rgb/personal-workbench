from collections.abc import Generator
from datetime import datetime, timezone
from decimal import Decimal
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from unittest.mock import patch

from alembic import command
from alembic.config import Config
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
import app.database as database
from app.collection.service import BATCH_RUNTIME
from app.collection.service import COLLECTION_LOCK
import app.competitors as competitors_module
from app.main import app
from app.models import Base, Competitor, CompetitorGroup, SystemSetting
from app.collection.types import ProductData, SkuData
from app.models import ChangeEvent, CollectionRun, ProductSnapshot, SkuSnapshot
from app.settings import get_competitor_monitoring_settings

BACKEND_ROOT = Path(__file__).parents[1]


def _run_revision(database_url: str, revision: str) -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    original_database_url = database.DATABASE_URL
    database.DATABASE_URL = database_url
    try:
        command.upgrade(config, revision)
    finally:
        database.DATABASE_URL = original_database_url


def _downgrade_revision(database_url: str, revision: str) -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    original_database_url = database.DATABASE_URL
    database.DATABASE_URL = database_url
    try:
        command.downgrade(config, revision)
    finally:
        database.DATABASE_URL = original_database_url


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


def test_own_shop_name_is_unconfigured_until_explicitly_saved(client):
    response = client[0].get("/api/settings/own-shop-name")

    assert response.status_code == 200
    assert response.json() == {"configured": False, "own_shop_name": None}


def test_own_shop_name_put_trims_and_round_trips(client):
    response = client[0].put(
        "/api/settings/own-shop-name",
        json={"own_shop_name": "  广州莓有科技有限公司  "},
    )

    assert response.status_code == 200
    assert response.json()["configured"] is True
    assert response.json()["own_shop_name"] == "广州莓有科技有限公司"
    assert client[0].get("/api/settings/own-shop-name").json() == {
        "configured": True,
        "own_shop_name": "广州莓有科技有限公司",
    }


def test_competitor_monitoring_settings_default_invalid_read_and_atomic_save(client):
    defaults = {
        "item_interval_seconds": 5,
        "continuous_collection_count": 10,
        "batch_rest_seconds": 120,
        "verification_cooldown_seconds": 600,
        "auto_resume_max": 2,
        "auto_collection_enabled": True,
        "auto_collection_strategy": "rolling_24h",
        "auto_collection_time": "09:30",
        "auto_collection_missed_policy": "catch_up",
    }
    assert client[0].get("/api/settings/competitor-monitoring").json() == defaults
    with client[1]() as session:
        session.add(SystemSetting(key="competitor_monitoring_item_interval_seconds", value="bad"))
        session.add(SystemSetting(key="competitor_monitoring_batch_rest_seconds", value="61"))
        session.commit()
    assert client[0].get("/api/settings/competitor-monitoring").json() == defaults

    saved = {"item_interval_seconds": 1, "continuous_collection_count": 50, "batch_rest_seconds": 0, "verification_cooldown_seconds": 3600, "auto_resume_max": 0, "auto_collection_enabled": False, "auto_collection_strategy": "fixed_daily", "auto_collection_time": "09:30", "auto_collection_missed_policy": "skip"}
    assert client[0].put("/api/settings/competitor-monitoring", json=saved).json() == saved
    rejected = client[0].put("/api/settings/competitor-monitoring", json={**saved, "item_interval_seconds": True})
    assert rejected.status_code == 422
    assert rejected.json()["field"] == "item_interval_seconds"
    assert client[0].get("/api/settings/competitor-monitoring").json() == saved


def test_competitor_monitoring_settings_falls_back_for_an_unbounded_legacy_integer_without_rewriting(client):
    raw = "9" * 5000
    with client[1]() as session:
        session.add(SystemSetting(key="competitor_monitoring_item_interval_seconds", value=raw))
        session.commit()

    response = client[0].get("/api/settings/competitor-monitoring")

    assert response.status_code == 200
    assert response.json()["item_interval_seconds"] == 5
    with client[1]() as session:
        assert session.get(SystemSetting, "competitor_monitoring_item_interval_seconds").value == raw


@pytest.mark.parametrize("field, malformed", [
    ("auto_collection_strategy", []),
    ("auto_collection_strategy", {}),
    ("auto_collection_strategy", True),
    ("auto_collection_missed_policy", []),
    ("auto_collection_missed_policy", {}),
    ("auto_collection_missed_policy", 1),
])
def test_competitor_monitoring_enum_malformed_json_is_422(client, field, malformed):
    payload = {
        "item_interval_seconds": 5, "continuous_collection_count": 10,
        "batch_rest_seconds": 120, "verification_cooldown_seconds": 600, "auto_resume_max": 2,
        "auto_collection_enabled": True, "auto_collection_strategy": "rolling_24h",
        "auto_collection_time": "09:30", "auto_collection_missed_policy": "catch_up",
    }
    payload[field] = malformed
    response = client[0].put("/api/settings/competitor-monitoring", json=payload)
    assert response.status_code == 422
    assert response.json()["field"] == field


def test_competitor_monitoring_settings_reads_the_complete_snapshot_in_one_query(client):
    saved = {
        "item_interval_seconds": 6,
        "continuous_collection_count": 8,
        "batch_rest_seconds": 180,
        "verification_cooldown_seconds": 720,
        "auto_resume_max": 1,
        "auto_collection_enabled": True,
        "auto_collection_strategy": "rolling_24h",
        "auto_collection_time": "09:30",
        "auto_collection_missed_policy": "catch_up",
    }
    assert client[0].put("/api/settings/competitor-monitoring", json=saved).status_code == 200
    with client[1]() as session, patch.object(session, "scalars", wraps=session.scalars) as scalars:
        assert get_competitor_monitoring_settings(session) == saved

    assert scalars.call_count == 1


@pytest.mark.parametrize("value", ["", "   ", "x" * 256])
def test_own_shop_name_rejects_empty_or_oversized_values_without_saving(client, value):
    response = client[0].put("/api/settings/own-shop-name", json={"own_shop_name": value})

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_own_shop_name"
    assert client[0].get("/api/settings/own-shop-name").json() == {
        "configured": False,
        "own_shop_name": None,
    }


def test_setting_save_reidentifies_known_shop_names_and_preserves_unknown(client):
    with client[1]() as session:
        session.add_all(
            [
                Competitor(
                    platform="1688", offer_id="self", url="https://detail.1688.com/offer/self.html",
                    shop_name="新店铺", ownership="competitor", group_id=None,
                    created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
                ),
                Competitor(
                    platform="1688", offer_id="unknown", url="https://detail.1688.com/offer/unknown.html",
                    shop_name=None, ownership="self", group_id=None,
                    created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
                ),
            ]
        )
        session.commit()

    response = client[0].put("/api/settings/own-shop-name", json={"own_shop_name": "新店铺"})

    assert response.status_code == 200
    with client[1]() as session:
        rows = {row.offer_id: row for row in session.scalars(select(Competitor)).all()}
        assert rows["self"].ownership == "self"
        assert rows["unknown"].ownership == "self"


def test_setting_reidentification_updates_timestamp_only_when_identity_changes(client):
    original_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with client[1]() as session:
        session.add(
            Competitor(
                platform="1688", offer_id="timestamp", url="https://detail.1688.com/offer/timestamp.html",
                shop_name="旧店铺", ownership="competitor", group_id=None,
                created_at=original_time, updated_at=original_time,
            )
        )
        session.commit()

    assert client[0].put("/api/settings/own-shop-name", json={"own_shop_name": "旧店铺"}).status_code == 200
    with client[1]() as session:
        changed_at = session.scalar(select(Competitor.updated_at).where(Competitor.offer_id == "timestamp"))
    assert changed_at is not None and changed_at > original_time.replace(tzinfo=None)

    assert client[0].put("/api/settings/own-shop-name", json={"own_shop_name": "旧店铺"}).status_code == 200
    with client[1]() as session:
        unchanged_at = session.scalar(select(Competitor.updated_at).where(Competitor.offer_id == "timestamp"))
    assert unchanged_at == changed_at


def _collected(offer_id: str, shop_name: str) -> ProductData:
    return ProductData(
        offer_id=offer_id,
        title="真实商品",
        shop_name=shop_name,
        main_image_url="https://img.example/item.jpg",
        image_urls=["https://img.example/item.jpg"],
        price_min=Decimal("10.00"),
        price_max=Decimal("12.00"),
        product_status="active",
        collection_source="html",
        captured_at=datetime(2026, 10, 4, tzinfo=timezone.utc),
        skus=[SkuData("sku-1", "红色", 3, Decimal("10.00"))],
    )


def _existing_competitor(
    session: Session,
    competitor_id: int,
    offer_id: str,
    *,
    ownership: str = "competitor",
    group_id: int | None = None,
    group_role: str = "competitor",
    shop_name: str | None = "旧店铺",
) -> Competitor:
    now = datetime.now(timezone.utc)
    competitor = Competitor(
        id=competitor_id,
        platform="1688",
        offer_id=offer_id,
        url=f"https://detail.1688.com/offer/{offer_id}.html",
        shop_name=shop_name,
        ownership=ownership,
        group_id=group_id,
        group_role=group_role,
        status="unknown",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    session.add(competitor)
    return competitor


def test_add_without_own_shop_name_is_fail_closed(client):
    with patch("app.collection.service.collect_1688_product") as collector:
        response = client[0].post(
            "/api/competitors",
            json={"url": "https://detail.1688.com/offer/123.html"},
        )

    assert response.status_code == 409
    assert response.json()["code"] == "own_shop_name_not_configured"
    collector.assert_not_called()
    with client[1]() as session:
        assert session.scalar(select(Competitor)) is None
        assert session.scalar(select(ProductSnapshot)) is None
        assert session.scalar(select(SkuSnapshot)) is None
        assert session.scalar(select(CollectionRun)) is None
        assert session.scalar(select(ChangeEvent)) is None


def test_add_real_self_persists_baseline_and_classifies_from_shop_name(client):
    assert client[0].put("/api/settings/own-shop-name", json={"own_shop_name": "我方 店铺"}).status_code == 200
    with patch("app.collection.service.collect_1688_product", return_value=_collected("123", "  我方  店铺 ")) as collector:
        response = client[0].post(
            "/api/competitors",
            json={"url": "https://detail.1688.com/offer/123.html"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["ownership"] == "self"
    assert body["group_id"] is None
    assert body["group_role"] == "competitor"
    assert body["title"] == "真实商品"
    collector.assert_called_once_with("https://detail.1688.com/offer/123.html", "123")
    with client[1]() as session:
        assert session.query(Competitor).count() == 1
        assert session.query(ProductSnapshot).count() == 1
        assert session.query(SkuSnapshot).count() == 1
        assert session.query(CollectionRun).count() == 1
        assert session.query(ChangeEvent).count() == 0


def test_add_other_shop_is_competitor(client):
    assert client[0].put("/api/settings/own-shop-name", json={"own_shop_name": "我方店铺"}).status_code == 200
    with patch("app.collection.service.collect_1688_product", return_value=_collected("124", "其他店铺")):
        response = client[0].post(
            "/api/competitors",
            json={"url": "https://detail.1688.com/offer/124.html"},
        )

    assert response.status_code == 201
    assert response.json()["ownership"] == "competitor"
    assert client[0].get("/api/competitors?ownership=self").json() == []
    assert len(client[0].get("/api/competitors?ownership=competitor").json()) == 1


def test_add_missing_shop_name_fails_closed_without_history(client):
    assert client[0].put("/api/settings/own-shop-name", json={"own_shop_name": "我方店铺"}).status_code == 200
    with patch("app.collection.service.collect_1688_product", return_value=_collected("125", "   ")):
        response = client[0].post(
            "/api/competitors",
            json={"url": "https://detail.1688.com/offer/125.html"},
        )

    assert response.status_code == 422
    assert response.json()["code"] == "shop_name_unavailable"
    with client[1]() as session:
        assert session.scalar(select(Competitor)) is None
        assert session.scalar(select(ProductSnapshot)) is None
        assert session.scalar(select(CollectionRun)) is None


def test_add_collector_failure_rolls_back_and_releases_collection_lock(client):
    assert client[0].put("/api/settings/own-shop-name", json={"own_shop_name": "我方店铺"}).status_code == 200
    with patch("app.collection.service.collect_1688_product", side_effect=RuntimeError("collector failed")):
        failed = client[0].post(
            "/api/competitors",
            json={"url": "https://detail.1688.com/offer/126.html"},
        )
    assert failed.status_code == 500
    assert failed.json()["code"] == "collection_failed"

    with patch("app.collection.service.collect_1688_product", return_value=_collected("126", "其他店铺")):
        recovered = client[0].post(
            "/api/competitors",
            json={"url": "https://detail.1688.com/offer/126.html"},
        )
    assert recovered.status_code == 201
    with client[1]() as session:
        assert session.query(Competitor).count() == 1
        assert session.query(ProductSnapshot).count() == 1
        assert session.query(CollectionRun).count() == 1


def test_successful_collection_reidentifies_ownership_and_group_atomically(client):
    assert client[0].put("/api/settings/own-shop-name", json={"own_shop_name": "我方店铺"}).status_code == 200
    with client[1]() as session:
        session.add_all([
            CompetitorGroup(id=1, name="空闲组", created_at=datetime.now(timezone.utc)),
            CompetitorGroup(id=2, name="legacy组", created_at=datetime.now(timezone.utc)),
            CompetitorGroup(id=3, name="真实组", created_at=datetime.now(timezone.utc)),
            CompetitorGroup(id=4, name="转竞品组", created_at=datetime.now(timezone.utc)),
        ])
        session.flush()
        _existing_competitor(session, 1, "collect-1")
        _existing_competitor(session, 2, "collect-2", group_id=1)
        _existing_competitor(session, 3, "collect-3", group_id=2)
        _existing_competitor(session, 4, "collect-4", ownership="self", group_id=2, group_role="own", shop_name=None)
        _existing_competitor(session, 5, "collect-5", group_id=3)
        _existing_competitor(session, 6, "collect-6", ownership="self", group_id=3, group_role="own", shop_name="我方店铺")
        _existing_competitor(session, 7, "collect-7", ownership="self", group_id=4, group_role="own", shop_name="我方店铺")
        session.commit()

    def collected(_url: str, offer_id: str) -> ProductData:
        return _collected(offer_id, "其他店铺" if offer_id == "collect-7" else "我方店铺")

    with patch("app.collection.service.collect_1688_product", side_effect=collected):
        for competitor_id in (1, 2, 3, 5, 7):
            response = client[0].post(f"/api/competitors/{competitor_id}/collect")
            assert response.status_code == 200, f"{competitor_id}: {response.text}"

    with client[1]() as session:
        rows = {
            row.id: (row.ownership, row.group_id, row.group_role)
            for row in session.scalars(select(Competitor).order_by(Competitor.id)).all()
        }
        assert rows[1] == ("self", None, "competitor")
        assert rows[2] == ("self", 1, "own")
        assert rows[3] == ("self", 2, "own")
        assert rows[4] == ("self", None, "competitor")
        assert rows[5] == ("self", None, "competitor")
        assert rows[6] == ("self", 3, "own")
        assert rows[7] == ("competitor", 4, "competitor")
        assert session.scalar(select(ChangeEvent)) is None
        assert session.query(ProductSnapshot).count() == 5
        assert session.query(CollectionRun).count() == 5


def test_successful_collection_without_own_shop_setting_preserves_ownership_and_saves_facts(client):
    with client[1]() as session:
        _existing_competitor(session, 1, "collect-no-setting", ownership="self")
        session.commit()

    with patch("app.collection.service.collect_1688_product", return_value=_collected("collect-no-setting", "其他店铺")):
        response = client[0].post("/api/competitors/1/collect")

    assert response.status_code == 200
    with client[1]() as session:
        row = session.get(Competitor, 1)
        assert row is not None
        assert (row.ownership, row.group_id, row.group_role) == ("self", None, "competitor")
        assert session.scalar(select(ProductSnapshot)) is not None
        assert session.scalar(select(CollectionRun)) is not None
        assert session.scalar(select(ChangeEvent)) is None


def test_add_final_validation_reads_own_shop_name_after_collector_transaction(client):
    assert client[0].put("/api/settings/own-shop-name", json={"own_shop_name": "采集前店铺"}).status_code == 200
    collector_entered = Event()
    release_collector = Event()
    responses = []

    def blocking_collect(_url, _offer_id):
        collector_entered.set()
        assert release_collector.wait(timeout=2)
        return _collected("130", "采集前店铺")

    with patch("app.competitors.collect_product", side_effect=blocking_collect):
        request_thread = Thread(
            target=lambda: responses.append(
                client[0].post("/api/competitors", json={"url": "https://detail.1688.com/offer/130.html"})
            )
        )
        request_thread.start()
        assert collector_entered.wait(timeout=2)
        with client[1]() as session:
            setting = session.get(SystemSetting, "own_shop_name")
            assert setting is not None
            setting.value = "采集期间新店铺"
            session.commit()
        release_collector.set()
        request_thread.join(timeout=2)

    assert len(responses) == 1
    assert responses[0].status_code == 201
    assert responses[0].json()["ownership"] == "competitor"
    with client[1]() as session:
        assert session.get(Competitor, 1).ownership == "competitor"


def test_add_final_validation_reads_deleted_group_after_collector_transaction(client):
    assert client[0].put("/api/settings/own-shop-name", json={"own_shop_name": "我方店铺"}).status_code == 200
    group = client[0].post("/api/competitor-groups", json={"name": "采集期间删除"}).json()
    collector_entered = Event()
    release_collector = Event()
    responses = []

    def blocking_collect(_url, _offer_id):
        collector_entered.set()
        assert release_collector.wait(timeout=2)
        return _collected("131", "其他店铺")

    with patch("app.competitors.collect_product", side_effect=blocking_collect):
        request_thread = Thread(
            target=lambda: responses.append(
                client[0].post(
                    "/api/competitors",
                    json={"url": "https://detail.1688.com/offer/131.html", "group_id": group["id"]},
                )
            )
        )
        request_thread.start()
        assert collector_entered.wait(timeout=2)
        with client[1]() as session:
            target_group = session.get(CompetitorGroup, group["id"])
            assert target_group is not None
            session.delete(target_group)
            session.commit()
        release_collector.set()
        request_thread.join(timeout=2)

    assert len(responses) == 1
    assert responses[0].status_code == 404
    assert responses[0].json()["code"] == "competitor_group_not_found"
    with client[1]() as session:
        assert session.scalar(select(Competitor)) is None
        assert session.scalar(select(ProductSnapshot)) is None
        assert session.scalar(select(SkuSnapshot)) is None
        assert session.scalar(select(CollectionRun)) is None


def test_add_integrity_error_without_duplicate_or_own_conflict_is_save_failure(client, monkeypatch):
    assert client[0].put("/api/settings/own-shop-name", json={"own_shop_name": "我方店铺"}).status_code == 200

    def fail_commit(_session):
        raise IntegrityError("forced", {}, RuntimeError("unrelated constraint"))

    monkeypatch.setattr(competitors_module.Session, "commit", fail_commit)
    with patch("app.collection.service.collect_1688_product", return_value=_collected("127", "其他店铺")):
        response = client[0].post(
            "/api/competitors",
            json={"url": "https://detail.1688.com/offer/127.html"},
        )

    assert response.status_code == 500
    assert response.json()["code"] == "collection_save_failed"
    with client[1]() as session:
        assert session.scalar(select(Competitor)) is None
        assert session.scalar(select(ProductSnapshot)) is None
        assert session.scalar(select(CollectionRun)) is None


def test_batch_reservation_rejects_add_before_collector_without_sleep(client):
    assert client[0].put("/api/settings/own-shop-name", json={"own_shop_name": "我方店铺"}).status_code == 200
    assert BATCH_RUNTIME.reserve([1]) is True
    try:
        with patch("app.competitors.collect_product") as collector:
            response = client[0].post(
                "/api/competitors",
                json={"url": "https://detail.1688.com/offer/128.html"},
            )
        assert response.status_code == 409
        assert response.json()["code"] == "collection_in_progress"
        collector.assert_not_called()
    finally:
        BATCH_RUNTIME.finish("success")


def test_batch_reservation_rejects_single_collection_before_collector(client):
    with client[1]() as session:
        session.add(
            Competitor(
                id=98, platform="1688", offer_id="single-batch", url="https://detail.1688.com/offer/single-batch.html",
                shop_name="其他店铺", ownership="competitor", group_id=None, status="unknown", is_active=True,
                created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

    assert BATCH_RUNTIME.reserve([98]) is True
    try:
        with patch("app.collection.service.collect_1688_product") as collector:
            response = client[0].post("/api/competitors/98/collect")
        assert response.status_code == 409
        assert response.json()["code"] == "collection_in_progress"
        collector.assert_not_called()
        with client[1]() as session:
            assert session.scalar(select(CollectionRun)) is None
    finally:
        BATCH_RUNTIME.finish("success")


def test_add_collection_lock_rejects_batch_reservation_without_sleep(client):
    assert client[0].put("/api/settings/own-shop-name", json={"own_shop_name": "我方店铺"}).status_code == 200
    with client[1]() as session:
        session.add(
            Competitor(
                id=99, platform="1688", offer_id="batch", url="https://detail.1688.com/offer/batch.html",
                shop_name="其他店铺", ownership="competitor", group_id=None, status="unknown", is_active=True,
                created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

    collector_entered = Event()
    release_collector = Event()
    add_responses = []

    def blocking_collect(_url, _offer_id):
        collector_entered.set()
        assert release_collector.wait(timeout=2)
        return _collected("129", "其他店铺")

    with patch("app.competitors.collect_product", side_effect=blocking_collect):
        add_thread = Thread(
            target=lambda: add_responses.append(
                client[0].post("/api/competitors", json={"url": "https://detail.1688.com/offer/129.html"})
            )
        )
        add_thread.start()
        assert collector_entered.wait(timeout=2)
        batch = client[0].post(
            "/api/competitors/collect-batch",
            json={"mode": "selected", "competitor_ids": [99]},
        )
        release_collector.set()
        add_thread.join(timeout=2)

    assert batch.status_code == 409
    assert batch.json()["code"] == "collection_in_progress"
    assert len(add_responses) == 1
    assert add_responses[0].status_code == 201
    assert BATCH_RUNTIME.is_busy() is False
    assert COLLECTION_LOCK.acquire(blocking=False) is True
    COLLECTION_LOCK.release()


def test_ownership_migration_preserves_history_and_resolves_legacy_roles():
    with TemporaryDirectory() as directory:
        database_url = f"sqlite:///{Path(directory, 'migration.db').as_posix()}"
        _run_revision(database_url, "20260923_11")
        engine = create_engine(database_url)
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE system_settings (key VARCHAR(64) NOT NULL PRIMARY KEY, value VARCHAR(255))"
            ))
            connection.execute(text(
                "INSERT INTO system_settings (key, value) VALUES ('own_shop_name', '已有自定义店铺')"
            ))
            connection.execute(text("INSERT INTO competitor_groups (id, name, created_at) VALUES (1, 'A19', '2026-01-01')"))
            connection.execute(
                text(
                    "INSERT INTO competitors (group_id, group_role, platform, offer_id, url, title, shop_name, status, is_active, created_at, updated_at) "
                    "VALUES (1, 'own', '1688', 'legacy-null', 'u1', '一', NULL, 'unknown', 1, '2026-01-01', '2026-01-01')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO competitors (group_id, group_role, platform, offer_id, url, title, shop_name, status, is_active, created_at, updated_at) "
                    "VALUES (NULL, 'competitor', '1688', 'known-self', 'u2', '二', '已有自定义店铺', 'unknown', 1, '2026-01-02', '2026-01-02')"
                )
            )
            connection.execute(text(
                "INSERT INTO product_snapshots "
                "(id, competitor_id, captured_at, title, shop_name, main_image_url, price_min, price_max, product_status, collection_source) "
                "VALUES (41, 1, '2026-01-03', '历史快照', '历史店铺', 'https://img/41.jpg', 12.30, 15.60, 'active', 'html')"
            ))
            connection.execute(text(
                "INSERT INTO sku_snapshots (id, product_snapshot_id, sku_id, sku_name, stock, price) "
                "VALUES (51, 41, 'sku-41', '红色', 7, 13.20)"
            ))
            connection.execute(text(
                "INSERT INTO collection_runs "
                "(id, competitor_id, started_at, finished_at, status, error_type, error_message) "
                "VALUES (61, 1, '2026-01-03 10:00:00', '2026-01-03 10:01:00', 'success', NULL, NULL)"
            ))
            connection.execute(text(
                "INSERT INTO change_events "
                "(id, competitor_id, snapshot_id, change_type, entity_key, old_value, new_value, detected_at) "
                "VALUES (71, 1, 41, 'title_changed', NULL, '旧标题', '历史快照', '2026-01-03 10:02:00')"
            ))
            history_before = {
                "product_snapshots": connection.execute(text(
                    "SELECT id, competitor_id, captured_at, title, shop_name, main_image_url, price_min, price_max, product_status, collection_source "
                    "FROM product_snapshots"
                )).all(),
                "sku_snapshots": connection.execute(text(
                    "SELECT id, product_snapshot_id, sku_id, sku_name, stock, price FROM sku_snapshots"
                )).all(),
                "collection_runs": connection.execute(text(
                    "SELECT id, competitor_id, started_at, finished_at, status, error_type, error_message FROM collection_runs"
                )).all(),
                "change_events": connection.execute(text(
                    "SELECT id, competitor_id, snapshot_id, change_type, entity_key, old_value, new_value, detected_at FROM change_events"
                )).all(),
            }
        _run_revision(database_url, "head")
        with engine.begin() as connection:
            rows = connection.execute(text("SELECT offer_id, ownership, group_role FROM competitors ORDER BY id")).all()
            assert rows == [("legacy-null", "self", "own"), ("known-self", "self", "competitor")]
            assert connection.execute(text("SELECT value FROM system_settings WHERE key='own_shop_name'")).scalar_one() == "已有自定义店铺"
            assert connection.execute(text("SELECT COUNT(*) FROM product_snapshots")).scalar_one() == 1
            assert connection.execute(text("SELECT COUNT(*) FROM sku_snapshots")).scalar_one() == 1
            assert connection.execute(text("SELECT COUNT(*) FROM collection_runs")).scalar_one() == 1
            assert connection.execute(text("SELECT COUNT(*) FROM change_events")).scalar_one() == 1
            assert connection.execute(text(
                "SELECT id, competitor_id, captured_at, title, shop_name, main_image_url, price_min, price_max, product_status, collection_source "
                "FROM product_snapshots"
            )).all() == history_before["product_snapshots"]
            assert connection.execute(text(
                "SELECT id, product_snapshot_id, sku_id, sku_name, stock, price FROM sku_snapshots"
            )).all() == history_before["sku_snapshots"]
            assert connection.execute(text(
                "SELECT id, competitor_id, started_at, finished_at, status, error_type, error_message FROM collection_runs"
            )).all() == history_before["collection_runs"]
            assert connection.execute(text(
                "SELECT id, competitor_id, snapshot_id, change_type, entity_key, old_value, new_value, detected_at FROM change_events"
            )).all() == history_before["change_events"]
            assert connection.execute(text(
                "SELECT competitor_id, product_snapshot_id FROM sku_snapshots JOIN product_snapshots ON product_snapshots.id = sku_snapshots.product_snapshot_id"
            )).all() == [(1, 41)]
            assert connection.execute(text(
                "SELECT change_events.competitor_id, change_events.snapshot_id FROM change_events"
            )).all() == [(1, 41)]
        engine.dispose()


def test_ownership_migration_logs_group_conflict_and_moves_loser_to_unassigned(caplog):
    with TemporaryDirectory() as directory:
        database_url = f"sqlite:///{Path(directory, 'migration.db').as_posix()}"
        _run_revision(database_url, "20260923_11")
        engine = create_engine(database_url)
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO competitor_groups (id, name, created_at) VALUES (1, 'A19', '2026-01-01')"))
            connection.execute(text(
                "INSERT INTO competitors (id, group_id, group_role, platform, offer_id, url, title, shop_name, status, is_active, created_at, updated_at) "
                "VALUES (1, 1, 'own', '1688', 'migration-winner', 'u1', '一', '广州莓有科技有限公司', 'unknown', 1, '2026-01-01', '2026-01-01')"
            ))
            connection.execute(text(
                "INSERT INTO competitors (id, group_id, group_role, platform, offer_id, url, title, shop_name, status, is_active, created_at, updated_at) "
                "VALUES (2, 1, 'competitor', '1688', 'migration-loser', 'u2', '二', '广州莓有科技有限公司', 'unknown', 1, '2026-01-02', '2026-01-02')"
            ))
        with caplog.at_level(logging.WARNING):
            _run_revision(database_url, "head")
        assert "count=1" in caplog.text
        assert "group_id=1" in caplog.text
        assert "winner=1" in caplog.text
        assert "losing_self_ids=[2]" in caplog.text
        with engine.begin() as connection:
            rows = connection.execute(text("SELECT id, ownership, group_id, group_role FROM competitors ORDER BY id")).all()
            assert rows == [(1, "self", 1, "own"), (2, "self", None, "competitor")]
        engine.dispose()


def test_ownership_migration_uses_created_at_before_legacy_group_role(caplog):
    with TemporaryDirectory() as directory:
        database_url = f"sqlite:///{Path(directory, 'migration.db').as_posix()}"
        _run_revision(database_url, "20260923_11")
        engine = create_engine(database_url)
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO competitor_groups (id, name, created_at) VALUES (1, 'A19', '2026-01-01')"))
            connection.execute(text(
                "INSERT INTO competitors (id, group_id, group_role, platform, offer_id, url, title, shop_name, status, is_active, created_at, updated_at) "
                "VALUES (1, 1, 'competitor', '1688', 'created-first', 'u1', '一', '广州莓有科技有限公司', 'unknown', 1, '2026-01-01', '2026-01-01')"
            ))
            connection.execute(text(
                "INSERT INTO competitors (id, group_id, group_role, platform, offer_id, url, title, shop_name, status, is_active, created_at, updated_at) "
                "VALUES (2, 1, 'own', '1688', 'legacy-role-first', 'u2', '二', '广州莓有科技有限公司', 'unknown', 1, '2026-01-02', '2026-01-02')"
            ))
        with caplog.at_level(logging.WARNING):
            _run_revision(database_url, "head")
        assert "winner=1" in caplog.text
        assert "losing_self_ids=[2]" in caplog.text
        with engine.begin() as connection:
            rows = connection.execute(text("SELECT id, ownership, group_id, group_role FROM competitors ORDER BY id")).all()
            assert rows == [(1, "self", 1, "own"), (2, "self", None, "competitor")]
        engine.dispose()


def test_ownership_migration_downgrade_refuses_existing_self_data():
    with TemporaryDirectory() as directory:
        database_url = f"sqlite:///{Path(directory, 'migration.db').as_posix()}"
        _run_revision(database_url, "head")
        engine = create_engine(database_url)
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO competitors (ownership, group_role, platform, offer_id, url, status, is_active, created_at, updated_at) "
                "VALUES ('self', 'competitor', '1688', 'downgrade-self', 'u', 'unknown', 1, '2026-01-01', '2026-01-01')"
            ))
        engine.dispose()
        with pytest.raises(RuntimeError, match="contains self ownership data"):
            _downgrade_revision(database_url, "20260923_11")
