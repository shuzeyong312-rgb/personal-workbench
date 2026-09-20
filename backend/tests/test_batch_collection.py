from collections.abc import Generator
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.collection.service import (
    BATCH_RUNTIME,
    COLLECTION_LOCK,
    BatchItemResult,
    BatchRuntime,
    CollectionError,
    run_batch_collection,
)
from app.database import get_db
from app.main import app
from app.collection.types import ProductData
from app.models import Base, Competitor, ProductSnapshot


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
    BATCH_RUNTIME.finish("success")
    with TestClient(app) as test_client:
        yield test_client, session_factory
    BATCH_RUNTIME.request_stop()
    BATCH_RUNTIME.mark_runner_stopped()
    app.dependency_overrides.clear()
    engine.dispose()


def add_competitor(session_factory: sessionmaker[Session], competitor_id: int | None = None, active: bool = True) -> int:
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        competitor = Competitor(
            id=competitor_id,
            platform="1688",
            offer_id=str(1000000000000 + (competitor_id or 1)),
            url=f"https://detail.1688.com/offer/{1000000000000 + (competitor_id or 1)}.html",
            status="unknown",
            is_active=active,
            created_at=now,
            updated_at=now,
        )
        session.add(competitor)
        session.commit()
        return competitor.id


def test_selected_batch_validates_as_a_whole_and_returns_202(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    add_competitor(client[1], 1)
    add_competitor(client[1], 2)
    with patch("app.competitors.start_batch_task") as start:
        response = client[0].post(
            "/api/competitors/collect-batch",
            json={"mode": "selected", "competitor_ids": [1, 2, 1]},
        )

    assert response.status_code == 202
    assert response.json()["status"] == "running"
    assert response.json()["total"] == 2
    start.assert_called_once()
    assert client[0].get("/api/competitors/collect-batch/status").json()["completed"] == 0


def test_selected_not_found_and_inactive_are_rejected_without_starting(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    add_competitor(client[1], 1, active=False)
    with patch("app.competitors.start_batch_task") as start:
        missing = client[0].post(
            "/api/competitors/collect-batch",
            json={"mode": "selected", "competitor_ids": [1, 99]},
        )
        inactive = client[0].post(
            "/api/competitors/collect-batch",
            json={"mode": "selected", "competitor_ids": [1]},
        )

    assert missing.status_code == 404
    assert missing.json()["code"] == "competitor_not_found"
    assert missing.json()["competitor_ids"] == [99]
    assert inactive.status_code == 409
    assert inactive.json()["code"] == "competitor_inactive"
    assert inactive.json()["competitor_ids"] == [1]
    start.assert_not_called()


def test_all_active_empty_returns_completed_without_starting(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    add_competitor(client[1], 1, active=False)
    with patch("app.competitors.start_batch_task") as start:
        response = client[0].post(
            "/api/competitors/collect-batch",
            json={"mode": "all_active"},
        )

    assert response.status_code == 202
    assert response.json()["status"] == "completed"
    assert response.json()["total"] == 0
    start.assert_not_called()


def test_batch_busy_uses_collection_in_progress(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    add_competitor(client[1], 1)
    BATCH_RUNTIME.reserve([1])
    response = client[0].post(
        "/api/competitors/collect-batch",
        json={"mode": "all_active"},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "collection_in_progress"


class FakeContext:
    def __init__(self) -> None:
        self.pages = [object()]
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakePlaywright:
    def __init__(self, context: FakeContext) -> None:
        self.context = context
        self.chromium = self
        self.launch_count = 0

    def __enter__(self) -> "FakePlaywright":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def launch_persistent_context(self, **_kwargs: object) -> FakeContext:
        self.launch_count += 1
        return self.context


def test_runner_reuses_one_browser_and_continues_after_ordinary_failure(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    add_competitor(client[1], 1)
    add_competitor(client[1], 2)
    runtime = BatchRuntime()
    runtime.reserve([1, 2])
    playwright = FakePlaywright(FakeContext())
    collect = Mock(
        side_effect=[
            CollectionError("collection_timeout", "商品页面加载超时"),
            SimpleNamespace(),
        ]
    )

    with patch("app.collection.service.sync_playwright", return_value=playwright), patch(
        "app.collection.service.move_context_offscreen"
    ), patch("app.collection.service.collect_competitor", collect):
        run_batch_collection(client[1], [1, 2], runtime)

    snapshot = runtime.snapshot()
    assert playwright.launch_count == 1
    assert collect.call_count == 2
    assert snapshot["status"] == "completed"
    assert snapshot["completed"] == 2
    assert snapshot["succeeded"] == 1
    assert snapshot["failed"] == 1
    assert snapshot["remaining"] == 0
    acquired = COLLECTION_LOCK.acquire(blocking=False)
    assert acquired
    COLLECTION_LOCK.release()


def test_batch_success_marks_each_saved_product_active(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    add_competitor(client[1], 1)
    add_competitor(client[1], 2)
    runtime = BatchRuntime()
    runtime.reserve([1, 2])
    playwright = FakePlaywright(FakeContext())
    collected = [
        ProductData(
            offer_id="1000000000001",
            title="商品一",
            shop_name="店铺一",
            main_image_url=None,
            price_min=Decimal("10.00"),
            price_max=Decimal("10.00"),
            product_status="unknown",
            collection_source="html",
            captured_at=datetime(2026, 9, 19, 1, tzinfo=timezone.utc),
            skus=[],
        ),
        ProductData(
            offer_id="1000000000002",
            title="商品二",
            shop_name="店铺二",
            main_image_url=None,
            price_min=Decimal("20.00"),
            price_max=Decimal("20.00"),
            product_status="unknown",
            collection_source="html",
            captured_at=datetime(2026, 9, 19, 2, tzinfo=timezone.utc),
            skus=[],
        ),
    ]

    with patch("app.collection.service.sync_playwright", return_value=playwright), patch(
        "app.collection.service.move_context_offscreen"
    ), patch("app.collection.service.collect_1688_product", side_effect=collected):
        run_batch_collection(client[1], [1, 2], runtime)

    with client[1]() as session:
        assert [session.get(Competitor, competitor_id).status for competitor_id in (1, 2)] == [
            "active",
            "active",
        ]
        assert session.scalars(select(ProductSnapshot)).all()
        assert {
            snapshot.product_status
            for snapshot in session.scalars(select(ProductSnapshot)).all()
        } == {"active"}


def test_verification_stops_remaining_items_and_keeps_lock_until_context_cleanup(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    add_competitor(client[1], 1)
    add_competitor(client[1], 2)
    runtime = BatchRuntime()
    runtime.reserve([1, 2])
    context = FakeContext()
    playwright = FakePlaywright(context)
    collect = Mock(side_effect=[CollectionError("1688_verification_required", "需要验证")])

    def restore(_context: object, _page: object | None) -> None:
        context.pages.clear()

    with patch("app.collection.service.sync_playwright", return_value=playwright), patch(
        "app.collection.service.move_context_offscreen"
    ), patch("app.collection.service.restore_context_window", side_effect=restore), patch(
        "app.collection.service.collect_competitor", collect
    ):
        run_batch_collection(client[1], [1, 2], runtime)

    snapshot = runtime.snapshot()
    assert snapshot["status"] == "verification_required"
    assert snapshot["completed"] == 1
    assert snapshot["remaining"] == 1
    assert collect.call_count == 1
    assert runtime.is_busy() is False
