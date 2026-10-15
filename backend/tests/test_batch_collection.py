from collections.abc import Generator
from datetime import datetime, timezone
from decimal import Decimal
import asyncio
from types import SimpleNamespace
from threading import Event, Thread
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.collection.service import (
    BATCH_RUNTIME,
    COLLECTION_LOCK,
    BatchConfig,
    BatchItemResult,
    BatchRuntime,
    CollectionError,
    _finalize_persisted_batch,
    create_collection_batch,
    recover_interrupted_batches,
    run_batch_collection,
)
import app.collection.service as collection_service
import app.competitors as competitors_module
from app.database import get_db
from app.main import app
from app.collection.types import ProductData
from app.collection.types import CollectionPageResult, OperatingMetricData
from app.models import Base, CollectionBatch, CollectionBatchItem, CollectionRun, Competitor, OperatingMetricObservation, ProductSnapshot
from app.settings import batch_config_values, update_competitor_monitoring_setting


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
    app.state.collection_session_factory = session_factory
    BATCH_RUNTIME.finish("success")
    test_client = TestClient(app)
    try:
        yield test_client, session_factory
    finally:
        test_client.close()
        BATCH_RUNTIME.request_stop()
        BATCH_RUNTIME.mark_runner_stopped()
        app.dependency_overrides.clear()
        app.state.collection_session_factory = None
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


def _collected_product(offer_id: str) -> ProductData:
    return ProductData(
        offer_id=offer_id,
        title="已采集商品",
        shop_name="测试店铺",
        main_image_url=None,
        price_min=Decimal("10.00"),
        price_max=Decimal("10.00"),
        product_status="active",
        collection_source="html",
        captured_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
        skus=[],
    )


@pytest.mark.parametrize(
    ("collector_result", "expected_error"),
    [
        ("success", None),
        (collection_service.CollectionTimeoutError(), "collection_timeout"),
        (collection_service.VerificationRequiredError(), "1688_verification_required"),
    ],
    ids=["success", "ordinary_failure", "verification"],
)
def test_collect_competitor_reports_external_access_before_each_external_outcome(
    client: tuple[TestClient, sessionmaker[Session]],
    collector_result: str | BaseException,
    expected_error: str | None,
) -> None:
    competitor_id = add_competitor(client[1], 1)
    observed: list[str] = []

    def external_collector(*_args: object, **_kwargs: object) -> ProductData:
        _kwargs["on_navigation_claim"]()
        _kwargs["on_navigation_confirmed"]()
        observed.append("collector")
        assert observed == ["callback", "collector"]
        if isinstance(collector_result, BaseException):
            raise collector_result
        return _collected_product("1000000000001")

    with client[1]() as session, patch.object(collection_service, "collect_1688_product", side_effect=external_collector):
        if expected_error is None:
            result = collection_service.collect_competitor(
                session, competitor_id, on_external_access=lambda: observed.append("callback")
            )
            assert result.outcome == "active"
        else:
            with pytest.raises(CollectionError) as error:
                collection_service.collect_competitor(
                    session, competitor_id, on_external_access=lambda: observed.append("callback")
                )
            assert error.value.code == expected_error

    assert observed == ["callback", "collector"]


def test_collect_competitor_reports_external_access_when_the_following_save_fails(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    competitor_id = add_competitor(client[1], 1)
    observed: list[str] = []
    with client[1]() as session:
        original_commit = session.commit
        commits = 0
        failed_once = False

        def commit() -> None:
            nonlocal commits, failed_once
            commits += 1
            if observed == ["callback", "collector"] and not failed_once:
                failed_once = True
                raise RuntimeError("save failed")
            original_commit()

        def external_collector(*_args: object, **_kwargs: object) -> ProductData:
            _kwargs["on_navigation_claim"]()
            _kwargs["on_navigation_confirmed"]()
            observed.append("collector")
            assert observed == ["callback", "collector"]
            return _collected_product("1000000000001")

        with patch.object(session, "commit", side_effect=commit), patch.object(
            collection_service, "collect_1688_product", side_effect=external_collector
        ), pytest.raises(CollectionError) as error:
            collection_service.collect_competitor(
                session, competitor_id, on_external_access=lambda: observed.append("callback")
            )

    assert error.value.code == "collection_save_failed"
    assert observed == ["callback", "collector"]


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
    assert response.json()["auto_resume_attempt"] == 0
    assert response.json()["auto_resume_max"] == 2
    assert response.json()["cooldown_remaining_seconds"] == 0
    start.assert_called_once()
    assert client[0].get("/api/competitors/collect-batch/status").json()["completed"] == 0


def test_pause_and_resume_batch_endpoints_return_authoritative_status(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    BATCH_RUNTIME.reserve([1])
    paused = client[0].post("/api/competitors/collect-batch/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    resumed = client[0].post("/api/competitors/collect-batch/resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "running"
    BATCH_RUNTIME.finish("success")


def test_batch_counts_each_terminal_item_in_its_operating_metrics_status():
    statuses = ("not_attempted", "success", "partial", "no_values", "failed", "blocked")
    runtime = BatchRuntime()
    runtime.reserve(list(range(1, len(statuses) + 1)))
    for competitor_id, operating_status in enumerate(statuses, 1):
        runtime.record(BatchItemResult(competitor_id, "success", operating_metrics_status=operating_status))

    snapshot = runtime.snapshot()
    assert snapshot["completed"] == len(statuses)
    assert sum(snapshot["operating_metrics_counts"].values()) == snapshot["completed"]
    assert snapshot["operating_metrics_counts"] == {status: 1 for status in statuses}


@pytest.mark.parametrize("operating_status", ["partial", "no_values"])
def test_batch_partial_success_when_base_collection_succeeds(
    client: tuple[TestClient, sessionmaker[Session]], operating_status: str,
) -> None:
    competitor_id = add_competitor(client[1], 1)
    runtime = BatchRuntime()
    runtime.reserve([competitor_id])
    result = SimpleNamespace(outcome="active", operating_metrics_status=operating_status)

    def collect(_db: Session, _competitor_id: int, *, on_external_access: object = None, **_kwargs: object) -> SimpleNamespace:
        assert callable(on_external_access)
        on_external_access()
        return result

    with patch.object(collection_service, "sync_playwright", return_value=FakePlaywright(FakeContext())), \
        patch.object(collection_service, "move_context_offscreen"), \
        patch.object(collection_service, "collect_competitor", side_effect=collect):
        run_batch_collection(client[1], [competitor_id], runtime, config=_test_config(item_interval_seconds=0, batch_rest_seconds=0))

    snapshot = runtime.snapshot()
    assert snapshot["status"] == "completed"
    assert snapshot["outcome_code"] == "partial_success"


def test_five_successful_base_items_with_mixed_operating_status_finish_partial_success(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    competitor_ids = [add_competitor(client[1], competitor_id) for competitor_id in range(1, 6)]
    statuses = ["success", "success", "partial", "partial", "failed"]
    runtime = BatchRuntime()
    runtime.reserve(competitor_ids)

    def collect(_db: Session, competitor_id: int, *, on_external_access: object = None, **_kwargs: object) -> SimpleNamespace:
        assert callable(on_external_access)
        on_external_access()
        return SimpleNamespace(outcome="active", operating_metrics_status=statuses[competitor_id - 1])

    with patch.object(collection_service, "sync_playwright", return_value=FakePlaywright(FakeContext())), \
        patch.object(collection_service, "move_context_offscreen"), \
        patch.object(collection_service, "collect_competitor", side_effect=collect):
        run_batch_collection(client[1], competitor_ids, runtime, config=_test_config(item_interval_seconds=0, batch_rest_seconds=0))

    snapshot = runtime.snapshot()
    assert snapshot["succeeded"] == 5
    assert snapshot["failed"] == 0
    assert snapshot["operating_metrics_counts"] == {
        "not_attempted": 0, "success": 2, "partial": 2, "no_values": 0, "failed": 1, "blocked": 0,
    }
    assert snapshot["outcome_code"] == "partial_success"


def test_batch_base_failure_takes_priority_over_partial_operating_metrics(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    competitor_id = add_competitor(client[1], 1)
    runtime = BatchRuntime()
    runtime.reserve([competitor_id])

    with patch.object(collection_service, "sync_playwright", return_value=FakePlaywright(FakeContext())), \
        patch.object(collection_service, "move_context_offscreen"), \
        patch.object(collection_service, "collect_competitor", side_effect=CollectionError(
            "collection_failed", "基础采集失败", operating_metrics_status="partial"
        )):
        run_batch_collection(client[1], [competitor_id], runtime, config=_test_config(item_interval_seconds=0, batch_rest_seconds=0))

    snapshot = runtime.snapshot()
    assert snapshot["status"] == "completed"
    assert snapshot["outcome_code"] == "partial_failure"


def test_end_batch_endpoint_requests_safe_shutdown(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    BATCH_RUNTIME.reserve([1])
    response = client[0].post("/api/competitors/collect-batch/end")
    assert response.status_code == 200
    assert response.json()["status"] == "stopping"
    assert BATCH_RUNTIME.stop_requested()
    BATCH_RUNTIME.finish("user_ended", status="stopped")


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


def test_all_active_batch_includes_active_self_and_competitor(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    own_id = add_competitor(client[1], 1)
    add_competitor(client[1], 2)
    with client[1]() as session:
        own = session.get(Competitor, own_id)
        assert own is not None
        own.ownership = "self"
        session.commit()

    with patch("app.competitors.start_batch_task") as start:
        response = client[0].post(
            "/api/competitors/collect-batch",
            json={"mode": "all_active"},
        )

    assert response.status_code == 202
    assert response.json()["total"] == 2
    assert start.call_args.args[1] == [1, 2]


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


def test_reserved_batch_blocks_delete_during_worker_handoff_and_worker_recovers(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    competitor_id = add_competitor(client[1], 1)
    worker_waiting = Event()
    allow_worker = Event()
    collected: list[int] = []
    real_acquire = collection_service.acquire_collection_slot
    gate = {"first": True}

    def gate_worker_acquire(*, batch_reservation: int | None = None, **kwargs: object) -> bool:
        if batch_reservation is not None and gate["first"]:
            gate["first"] = False
            worker_waiting.set()
            assert allow_worker.wait(timeout=2)
        return real_acquire(batch_reservation=batch_reservation, **kwargs)

    def fake_collect(_session: Session, item_id: int, **_kwargs: object) -> SimpleNamespace:
        collected.append(item_id)
        return SimpleNamespace(outcome="active")

    assert BATCH_RUNTIME.reserve([competitor_id]) is True
    worker = Thread(target=run_batch_collection, args=(client[1], [competitor_id], BATCH_RUNTIME))
    with patch.object(collection_service, "acquire_collection_slot", side_effect=gate_worker_acquire), \
        patch.object(collection_service, "sync_playwright", return_value=FakePlaywright(FakeContext())), \
        patch.object(collection_service, "move_context_offscreen"), \
        patch.object(collection_service, "collect_competitor", side_effect=fake_collect):
        worker.start()
        assert worker_waiting.wait(timeout=2)
        blocked = client[0].delete(f"/api/competitors/{competitor_id}")
        assert blocked.status_code == 409
        assert blocked.json()["code"] == "collection_in_progress"
        with client[1]() as session:
            assert session.get(Competitor, competitor_id) is not None
        allow_worker.set()
        worker.join(timeout=2)

    assert not worker.is_alive()
    assert collected == [competitor_id]
    assert BATCH_RUNTIME.is_busy() is False
    assert client[0].delete(f"/api/competitors/{competitor_id}").status_code == 204


class FakeContext:
    def __init__(self) -> None:
        self.pages = [object()]
        self.closed = False

    def close(self) -> None:
        self.closed = True
        self.pages.clear()


class FakePlaywright:
    def __init__(self, context: FakeContext | list[FakeContext]) -> None:
        self.contexts = context if isinstance(context, list) else [context]
        self.chromium = self
        self.launch_count = 0
        self.launch_kwargs: list[dict[str, object]] = []

    def __enter__(self) -> "FakePlaywright":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def launch_persistent_context(self, **kwargs: object) -> FakeContext:
        self.launch_count += 1
        self.launch_kwargs.append(kwargs)
        return self.contexts[min(self.launch_count - 1, len(self.contexts) - 1)]


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


def test_batch_keeps_operating_status_when_commit_expires_run_orm_fields(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    competitor_id = add_competitor(client[1], 1)
    client[1].configure(expire_on_commit=True)
    runtime = BatchRuntime()
    runtime.reserve([competitor_id])
    playwright = FakePlaywright(FakeContext())

    try:
        with patch("app.collection.service.sync_playwright", return_value=playwright), patch(
            "app.collection.service.move_context_offscreen"
        ), patch("app.collection.service.collect_1688_product", return_value=_collected_product("1000000000001")):
            run_batch_collection(client[1], [competitor_id], runtime)
    finally:
        client[1].configure(expire_on_commit=False)

    snapshot = runtime.snapshot()
    assert snapshot["status"] == "completed"
    assert snapshot["completed"] == 1
    assert snapshot["items"][0]["status"] == "success"
    assert snapshot["items"][0]["operating_metrics_status"] == "failed"


def test_verification_closes_context_and_enters_cooldown_without_completing_current_item(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    add_competitor(client[1], 1)
    add_competitor(client[1], 2)
    runtime = BatchRuntime()
    runtime.reserve([1, 2])
    context = FakeContext()
    retry_context = FakeContext()
    playwright = FakePlaywright([context, retry_context])
    collect = Mock(
        side_effect=[
            CollectionError("1688_verification_required", "需要验证"),
            SimpleNamespace(),
            SimpleNamespace(),
        ]
    )
    thread = Thread(
        target=run_batch_collection,
        args=(client[1], [1, 2], runtime),
        kwargs={"cooldown_seconds": 0.3},
    )

    with patch("app.collection.service.sync_playwright", return_value=playwright), patch(
        "app.collection.service.move_context_offscreen"
    ), patch("app.collection.service.collect_competitor", collect):
        thread.start()
        for _ in range(100):
            if runtime.snapshot()["status"] == "cooling_down":
                break
            runtime.wait_for_stop(0.01)
        cooling = runtime.snapshot()
        assert cooling["status"] == "cooling_down"
        assert cooling["auto_resume_attempt"] == 1
        assert cooling["cooldown_remaining_seconds"] > 0
        assert cooling["completed"] == 0
        assert cooling["remaining"] == 2
        assert cooling["verification_required"] == 0
        assert cooling["items"] == []
        assert context.closed is True
        assert collect.call_count == 1
        assert not COLLECTION_LOCK.acquire(blocking=False)
        thread.join(timeout=2)

    assert not thread.is_alive()
    snapshot = runtime.snapshot()
    assert playwright.launch_count == 2
    assert len(playwright.launch_kwargs) == 2
    assert playwright.launch_kwargs[0]["user_data_dir"] == playwright.launch_kwargs[1]["user_data_dir"]
    assert str(playwright.launch_kwargs[0]["user_data_dir"]).endswith(".browser-profile")
    assert playwright.launch_kwargs[0]["channel"] == playwright.launch_kwargs[1]["channel"] == "chrome"
    assert playwright.launch_kwargs[0]["headless"] == playwright.launch_kwargs[1]["headless"] is False
    assert [call.args[1] for call in collect.call_args_list] == [1, 1, 2]
    assert snapshot["status"] == "completed"
    assert snapshot["completed"] == 2
    assert snapshot["remaining"] == 0


def test_second_verification_enters_second_cooldown_and_final_verification_is_manual(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    add_competitor(client[1], 1)
    add_competitor(client[1], 2)
    runtime = BatchRuntime()
    runtime.reserve([1, 2])
    first_context, second_context, final_context = FakeContext(), FakeContext(), FakeContext()
    playwright = FakePlaywright([first_context, second_context, final_context])
    collect = Mock(
        side_effect=[
            CollectionError("1688_verification_required", "需要验证 1"),
            CollectionError("1688_verification_required", "需要验证 2"),
            CollectionError("1688_verification_required", "需要验证 3"),
        ]
    )

    with patch("app.collection.service.sync_playwright", return_value=playwright), patch(
        "app.collection.service.move_context_offscreen"
    ), patch("app.collection.service.restore_context_window", side_effect=lambda _context, _page: final_context.pages.clear()), patch(
        "app.collection.service.collect_competitor", collect
    ):
        run_batch_collection(client[1], [1, 2], runtime, cooldown_seconds=0)

    snapshot = runtime.snapshot()
    assert snapshot["status"] == "verification_required"
    assert snapshot["completed"] == 1
    assert snapshot["remaining"] == 1
    assert snapshot["auto_resume_attempt"] == 2
    assert snapshot["verification_required"] == 1
    assert snapshot["items"] == [
        {
            "competitor_id": 1,
            "status": "verification_required",
            "error_code": "1688_verification_required",
            "message": "需要验证 3",
            "outcome": None,
            "operating_metrics_status": "blocked",
        }
    ]
    assert collect.call_count == 3
    assert playwright.launch_count == 3
    assert runtime.is_busy() is False


def test_shutdown_interrupts_cooldown_and_releases_lock(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    add_competitor(client[1], 1)
    runtime = BatchRuntime()
    runtime.reserve([1])
    context = FakeContext()
    collect = Mock(side_effect=[CollectionError("1688_verification_required", "需要验证")])
    thread = Thread(
        target=run_batch_collection,
        args=(client[1], [1], runtime),
        kwargs={"cooldown_seconds": 30},
    )

    with patch("app.collection.service.sync_playwright", return_value=FakePlaywright(context)), patch(
        "app.collection.service.move_context_offscreen"
    ), patch("app.collection.service.collect_competitor", collect):
        thread.start()
        for _ in range(100):
            if runtime.snapshot()["status"] == "cooling_down":
                break
            runtime.wait_for_stop(0.01)
        assert runtime.snapshot()["status"] == "cooling_down"
        runtime.request_stop()
        thread.join(timeout=2)

    assert not thread.is_alive()
    assert context.closed is True
    assert runtime.is_busy() is False
    assert runtime.snapshot()["cooldown_remaining_seconds"] == 0
    assert COLLECTION_LOCK.acquire(blocking=False)
    COLLECTION_LOCK.release()


def test_cooling_down_rejects_all_other_collection_entrypoints(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    add_competitor(client[1], 1)
    runtime = BatchRuntime()
    runtime.reserve([1])
    context = FakeContext()
    batch_collect = Mock(side_effect=[CollectionError("1688_verification_required", "需要验证")])
    thread = Thread(
        target=run_batch_collection,
        args=(client[1], [1], runtime),
        kwargs={"cooldown_seconds": 30},
    )

    with patch("app.collection.service.sync_playwright", return_value=FakePlaywright(context)), patch(
        "app.collection.service.move_context_offscreen"
    ), patch("app.collection.service.collect_competitor", batch_collect):
        thread.start()
        for _ in range(100):
            if runtime.snapshot()["status"] == "cooling_down":
                break
            runtime.wait_for_stop(0.01)
        assert runtime.snapshot()["status"] == "cooling_down"

        second_batch = client[0].post(
            "/api/competitors/collect-batch",
            json={"mode": "selected", "competitor_ids": [1]},
        )
        single = client[0].post("/api/competitors/1/collect")
        delete_batch = client[0].post(
            "/api/competitors/delete-batch",
            json={"competitor_ids": [1]},
        )

        assert second_batch.status_code == 409
        assert second_batch.json()["code"] == "collection_in_progress"
        assert single.status_code == 409
        assert single.json()["code"] == "collection_in_progress"
        assert delete_batch.status_code == 409
        assert delete_batch.json()["code"] == "collection_in_progress"
        runtime.request_stop()
        thread.join(timeout=2)

    assert not thread.is_alive()
    assert runtime.is_busy() is False
    assert COLLECTION_LOCK.acquire(blocking=False)
    COLLECTION_LOCK.release()


def _test_config(**overrides: int) -> BatchConfig:
    values = {
        "item_interval_seconds": 5,
        "continuous_collection_count": 10,
        "batch_rest_seconds": 120,
        "verification_cooldown_seconds": 600,
        "auto_resume_max": 2,
        "operating_metrics_retry_max": 0,
    }
    values.update(overrides)
    return BatchConfig(**values)


def test_batch_start_freezes_one_settings_snapshot_and_the_next_start_uses_the_new_one(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    add_competitor(client[1], 1)
    auto = {"auto_collection_enabled": True, "auto_collection_strategy": "rolling_24h", "auto_collection_time": "09:30", "auto_collection_missed_policy": "catch_up"}
    old = {"item_interval_seconds": 1, "continuous_collection_count": 1, "batch_rest_seconds": 0, "verification_cooldown_seconds": 60, "auto_resume_max": 0, "operating_metrics_retry_max": 0, **auto}
    new = {"item_interval_seconds": 60, "continuous_collection_count": 50, "batch_rest_seconds": 1800, "verification_cooldown_seconds": 3600, "auto_resume_max": 5, "operating_metrics_retry_max": 0, **auto}
    assert client[0].put("/api/settings/competitor-monitoring", json=old).status_code == 200
    with patch("app.competitors.start_batch_task") as start:
        assert client[0].post("/api/competitors/collect-batch", json={"mode": "selected", "competitor_ids": [1]}).status_code == 202
        frozen = start.call_args.kwargs["config"]
        with client[1]() as settings_db:
            assert update_competitor_monitoring_setting(new, db=settings_db) == new
        assert frozen == BatchConfig(**batch_config_values(old))
        BATCH_RUNTIME.finish("success")
        assert client[0].post("/api/competitors/collect-batch", json={"mode": "selected", "competitor_ids": [1]}).status_code == 202

    assert start.call_args.kwargs["config"] == BatchConfig(**batch_config_values(new))


def test_batch_start_and_settings_put_interleaving_freeze_only_complete_old_or_new_configurations(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    add_competitor(client[1], 1)
    auto = {"auto_collection_enabled": True, "auto_collection_strategy": "rolling_24h", "auto_collection_time": "09:30", "auto_collection_missed_policy": "catch_up"}
    old = {"item_interval_seconds": 1, "continuous_collection_count": 1, "batch_rest_seconds": 0, "verification_cooldown_seconds": 60, "auto_resume_max": 0, "operating_metrics_retry_max": 0, **auto}
    new = {"item_interval_seconds": 60, "continuous_collection_count": 50, "batch_rest_seconds": 1800, "verification_cooldown_seconds": 3600, "auto_resume_max": 5, "operating_metrics_retry_max": 0, **auto}
    assert client[0].put("/api/settings/competitor-monitoring", json=old).status_code == 200
    snapshot_read = Event()
    resume_start = Event()
    responses = []
    real_get = competitors_module.get_competitor_monitoring_settings

    def pause_after_snapshot(db: Session) -> dict[str, int]:
        values = real_get(db)
        snapshot_read.set()
        assert resume_start.wait(timeout=2)
        return values

    with patch("app.competitors.start_batch_task") as start, patch.object(
        competitors_module, "get_competitor_monitoring_settings", side_effect=pause_after_snapshot
    ):
        worker = Thread(target=lambda: responses.append(client[0].post(
            "/api/competitors/collect-batch", json={"mode": "selected", "competitor_ids": [1]}
        )))
        worker.start()
        assert snapshot_read.wait(timeout=2)
        with client[1]() as settings_db:
            assert update_competitor_monitoring_setting(new, db=settings_db) == new
        resume_start.set()
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert responses[0].status_code == 202
        assert start.call_args.kwargs["config"] == BatchConfig(**batch_config_values(old))

    BATCH_RUNTIME.finish("success")
    with patch("app.competitors.start_batch_task") as next_start:
        assert client[0].post("/api/competitors/collect-batch", json={"mode": "selected", "competitor_ids": [1]}).status_code == 202
    assert next_start.call_args.kwargs["config"] == BatchConfig(**batch_config_values(new))


def test_batch_waits_are_driven_by_external_accesses_not_successes_and_skip_the_last_item(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    add_competitor(client[1], 1)
    add_competitor(client[1], 2)
    runtime = BatchRuntime()
    runtime.reserve([1, 2], _test_config())
    waits: list[tuple[str, float]] = []

    def collect(_db: Session, _id: int, *, on_external_access: object = None, **_kwargs: object) -> SimpleNamespace:
        assert callable(on_external_access)
        on_external_access()
        if _id == 1:
            raise CollectionError("collection_timeout", "普通失败")
        return SimpleNamespace(outcome="active")

    with patch.object(collection_service, "sync_playwright", return_value=FakePlaywright(FakeContext())), \
        patch.object(collection_service, "move_context_offscreen"), \
        patch.object(collection_service, "collect_competitor", side_effect=collect), \
        patch.object(runtime, "wait_for_stop", side_effect=lambda seconds: waits.append(("interval", seconds)) or False):
        run_batch_collection(client[1], [1, 2], runtime, config=_test_config(item_interval_seconds=7, batch_rest_seconds=0))

    assert waits == [("interval", 7)]
    assert runtime.external_accesses() == 2
    assert runtime.snapshot()["failed"] == 1


def test_resting_is_prioritized_over_interval_and_resets_before_the_next_access(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    for competitor_id in (1, 2, 3):
        add_competitor(client[1], competitor_id)
    runtime = BatchRuntime()
    config = _test_config(continuous_collection_count=1, batch_rest_seconds=120)
    runtime.reserve([1, 2, 3], config)
    waits: list[tuple[str, float]] = []

    def collect(_db: Session, _id: int, *, on_external_access: object = None, **_kwargs: object) -> SimpleNamespace:
        assert callable(on_external_access)
        on_external_access()
        return SimpleNamespace(outcome="active")

    with patch.object(collection_service, "sync_playwright", return_value=FakePlaywright(FakeContext())), \
        patch.object(collection_service, "move_context_offscreen"), \
        patch.object(collection_service, "collect_competitor", side_effect=collect), \
        patch.object(runtime, "wait_for_resting", side_effect=lambda seconds: waits.append(("rest", seconds)) or True), \
        patch.object(runtime, "wait_for_stop", side_effect=lambda seconds: waits.append(("interval", seconds)) or False):
        run_batch_collection(client[1], [1, 2, 3], runtime, config=config)

    assert waits == [("rest", 120), ("rest", 120)]
    assert runtime.snapshot()["status"] == "completed"


def test_verification_preempts_other_waits_then_retries_without_an_extra_wait(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    add_competitor(client[1], 1)
    add_competitor(client[1], 2)
    runtime = BatchRuntime()
    config = _test_config(continuous_collection_count=1, batch_rest_seconds=120, verification_cooldown_seconds=180)
    runtime.reserve([1, 2], config)
    calls: list[int] = []
    waits: list[tuple[str, float]] = []

    def collect(_db: Session, item_id: int, *, on_external_access: object = None, **_kwargs: object) -> SimpleNamespace:
        assert callable(on_external_access)
        on_external_access()
        calls.append(item_id)
        if calls == [1]:
            raise CollectionError("1688_verification_required", "需要验证")
        return SimpleNamespace(outcome="active")

    with patch.object(collection_service, "sync_playwright", return_value=FakePlaywright([FakeContext(), FakeContext()])), \
        patch.object(collection_service, "move_context_offscreen"), \
        patch.object(collection_service, "collect_competitor", side_effect=collect), \
        patch.object(runtime, "wait_for_cooldown", side_effect=lambda seconds: waits.append(("cooldown", seconds)) or True), \
        patch.object(runtime, "wait_for_resting", side_effect=lambda seconds: waits.append(("rest", seconds)) or True), \
        patch.object(runtime, "wait_for_stop", side_effect=lambda seconds: waits.append(("interval", seconds)) or False):
        run_batch_collection(client[1], [1, 2], runtime, config=config)

    assert calls == [1, 1, 2]
    assert waits == [("cooldown", 180), ("rest", 120)]


def test_zero_auto_resume_enters_manual_verification_without_cooldown(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    add_competitor(client[1], 1)
    runtime = BatchRuntime()
    config = _test_config(auto_resume_max=0)
    runtime.reserve([1], config)

    def verification(_db: Session, _id: int, *, on_external_access: object = None, **_kwargs: object) -> None:
        assert callable(on_external_access)
        on_external_access()
        raise CollectionError("1688_verification_required", "需要验证")

    context = FakeContext()
    with patch.object(collection_service, "sync_playwright", return_value=FakePlaywright(context)), \
        patch.object(collection_service, "move_context_offscreen"), \
        patch.object(collection_service, "restore_context_window", side_effect=lambda _context, _page: context.pages.clear()), \
        patch.object(collection_service, "collect_competitor", side_effect=verification), \
        patch.object(runtime, "wait_for_cooldown") as cooldown:
        run_batch_collection(client[1], [1], runtime, config=config)

    assert runtime.snapshot()["status"] == "verification_required"
    cooldown.assert_not_called()


def test_stop_interrupts_item_interval_before_the_next_collector_and_releases_resources(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    add_competitor(client[1], 1)
    add_competitor(client[1], 2)
    runtime = BatchRuntime()
    config = _test_config(item_interval_seconds=60, batch_rest_seconds=0)
    runtime.reserve([1, 2], config)
    context = FakeContext()
    interval_started = Event()
    calls: list[int] = []
    real_wait = runtime.wait_for_stop

    def collect(_db: Session, item_id: int, *, on_external_access: object = None, **_kwargs: object) -> SimpleNamespace:
        assert callable(on_external_access)
        on_external_access()
        calls.append(item_id)
        return SimpleNamespace(outcome="active")

    def wait(seconds: float) -> bool:
        interval_started.set()
        return real_wait(seconds)

    worker = Thread(target=run_batch_collection, args=(client[1], [1, 2], runtime), kwargs={"config": config})
    with patch.object(collection_service, "sync_playwright", return_value=FakePlaywright(context)), \
        patch.object(collection_service, "move_context_offscreen"), \
        patch.object(collection_service, "collect_competitor", side_effect=collect), \
        patch.object(runtime, "wait_for_stop", side_effect=wait):
        worker.start()
        assert interval_started.wait(timeout=2)
        runtime.request_stop()
        worker.join(timeout=2)

    assert not worker.is_alive()
    assert calls == [1]
    assert context.closed is True
    assert runtime.is_busy() is False
    assert COLLECTION_LOCK.acquire(blocking=False)
    COLLECTION_LOCK.release()


def test_stop_interrupts_resting_before_the_next_collector_and_releases_resources(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    add_competitor(client[1], 1)
    add_competitor(client[1], 2)
    runtime = BatchRuntime()
    config = _test_config(continuous_collection_count=1, batch_rest_seconds=60)
    runtime.reserve([1, 2], config)
    context = FakeContext()
    calls: list[int] = []
    resting_started = Event()
    real_enter_resting = runtime.enter_resting

    def collect(_db: Session, item_id: int, *, on_external_access: object = None, **_kwargs: object) -> SimpleNamespace:
        assert callable(on_external_access)
        on_external_access()
        calls.append(item_id)
        return SimpleNamespace(outcome="active")

    def enter_resting(seconds: float) -> None:
        real_enter_resting(seconds)
        resting_started.set()

    worker = Thread(target=run_batch_collection, args=(client[1], [1, 2], runtime), kwargs={"config": config})
    with patch.object(collection_service, "sync_playwright", return_value=FakePlaywright(context)), \
        patch.object(collection_service, "move_context_offscreen"), \
        patch.object(collection_service, "collect_competitor", side_effect=collect), \
        patch.object(runtime, "enter_resting", side_effect=enter_resting):
        worker.start()
        assert resting_started.wait(timeout=2)
        assert runtime.snapshot()["status"] == "resting"
        runtime.request_stop()
        worker.join(timeout=2)

    assert not worker.is_alive()
    assert calls == [1]
    assert context.closed is True
    assert runtime.is_busy() is False
    assert COLLECTION_LOCK.acquire(blocking=False)
    COLLECTION_LOCK.release()


def test_pause_waits_for_current_item_then_resumes_remaining_batch(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    add_competitor(client[1], 1)
    add_competitor(client[1], 2)
    runtime = BatchRuntime()
    runtime.reserve([1, 2])
    contexts = [FakeContext(), FakeContext()]
    first_started = Event()
    finish_first = Event()
    calls: list[int] = []

    def collect(_db: Session, item_id: int, *, on_external_access: object = None, **_kwargs: object) -> SimpleNamespace:
        assert callable(on_external_access)
        on_external_access()
        calls.append(item_id)
        if item_id == 1:
            first_started.set()
            assert finish_first.wait(2)
        return SimpleNamespace(outcome="active")

    worker = Thread(target=run_batch_collection, args=(client[1], [1, 2], runtime), kwargs={"config": _test_config(item_interval_seconds=0, batch_rest_seconds=0)})
    with patch.object(collection_service, "sync_playwright", return_value=FakePlaywright(contexts)), \
        patch.object(collection_service, "move_context_offscreen"), \
        patch.object(collection_service, "collect_competitor", side_effect=collect):
        worker.start()
        assert first_started.wait(timeout=2)
        assert runtime.request_pause()
        assert runtime.snapshot()["status"] == "pausing"
        finish_first.set()
        for _ in range(200):
            if runtime.snapshot()["status"] == "paused":
                break
            Event().wait(0.01)
        assert runtime.snapshot()["status"] == "paused"
        assert runtime.snapshot()["browser_open"] is False
        assert calls == [1]
        assert contexts[0].closed is True
        assert runtime.resume()
        worker.join(timeout=2)

    assert not worker.is_alive()
    assert calls == [1, 2]
    assert contexts[1].closed is True
    assert runtime.snapshot()["status"] == "completed"


def test_end_finishes_current_item_then_stops_remaining_batch(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    add_competitor(client[1], 1)
    add_competitor(client[1], 2)
    runtime = BatchRuntime()
    runtime.reserve([1, 2])
    context = FakeContext()
    first_started = Event()
    finish_first = Event()
    calls: list[int] = []

    def collect(_db: Session, item_id: int, *, on_external_access: object = None, **_kwargs: object) -> SimpleNamespace:
        assert callable(on_external_access)
        on_external_access()
        calls.append(item_id)
        if item_id == 1:
            first_started.set()
            assert finish_first.wait(2)
        return SimpleNamespace(outcome="active")

    worker = Thread(target=run_batch_collection, args=(client[1], [1, 2], runtime), kwargs={"config": _test_config(item_interval_seconds=0, batch_rest_seconds=0)})
    with patch.object(collection_service, "sync_playwright", return_value=FakePlaywright(context)), \
        patch.object(collection_service, "move_context_offscreen"), \
        patch.object(collection_service, "collect_competitor", side_effect=collect):
        worker.start()
        assert first_started.wait(timeout=2)
        assert runtime.request_end()
        assert runtime.snapshot()["status"] == "stopping"
        finish_first.set()
        worker.join(timeout=2)

    assert not worker.is_alive()
    assert calls == [1]
    assert context.closed is True
    assert runtime.snapshot()["status"] == "stopped"
    assert runtime.snapshot()["outcome_code"] == "user_ended"
    assert runtime.snapshot()["remaining"] == 1


@pytest.mark.parametrize(
    ("phase", "remaining_field"),
    [("cooldown", "cooldown_remaining_seconds"), ("resting", "resting_remaining_seconds")],
)
def test_pause_freezes_wait_countdown_until_resumed(phase: str, remaining_field: str) -> None:
    runtime = BatchRuntime()
    runtime.reserve([1])
    getattr(runtime, f"enter_{phase}")(2)
    worker = Thread(target=getattr(runtime, f"wait_for_{phase}"), args=(2,))
    worker.start()

    assert runtime.request_pause()
    for _ in range(100):
        if runtime.snapshot()["status"] == "paused":
            break
        Event().wait(0.01)
    paused_remaining = runtime.snapshot()[remaining_field]
    Event().wait(0.2)
    assert runtime.snapshot()[remaining_field] == paused_remaining

    assert runtime.resume()
    worker.join(timeout=3)
    assert not worker.is_alive()
    assert runtime.snapshot()["status"] == "running"


def test_pause_requested_during_last_item_does_not_hold_completed_batch(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    add_competitor(client[1], 1)
    runtime = BatchRuntime()
    runtime.reserve([1])
    context = FakeContext()

    def collect(_db: Session, _item_id: int, *, on_external_access: object = None, **_kwargs: object) -> SimpleNamespace:
        assert callable(on_external_access)
        on_external_access()
        assert runtime.request_pause()
        return SimpleNamespace(outcome="active")

    worker = Thread(target=run_batch_collection, args=(client[1], [1], runtime), kwargs={"config": _test_config(item_interval_seconds=0, batch_rest_seconds=0)})
    with patch.object(collection_service, "sync_playwright", return_value=FakePlaywright(context)), \
        patch.object(collection_service, "move_context_offscreen"), \
        patch.object(collection_service, "collect_competitor", side_effect=collect):
        worker.start()
        worker.join(timeout=2)

    assert not worker.is_alive()
    assert runtime.snapshot()["status"] == "completed"
    assert runtime.snapshot()["remaining"] == 0


def test_persisted_batch_deduplicates_products_and_exposes_history_api(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    add_competitor(client[1], 1)
    config = BatchConfig(item_interval_seconds=1, continuous_collection_count=2, batch_rest_seconds=0)
    with client[1]() as db:
        batch = create_collection_batch(db, [1, 1], config, trigger_kind="manual_selected")
        batch_id = batch.id
        task_id = batch.task_id
        items = db.query(CollectionBatchItem).filter_by(batch_id=batch_id).all()
        assert batch.planned_products == 1
        assert [(item.position, item.competitor_id) for item in items] == [(0, 1)]

    page = client[0].get("/api/collection-batches")
    assert page.status_code == 200
    assert page.json()["total"] == 1
    assert page.json()["items"][0]["batch_id"] == batch_id
    assert page.json()["items"][0]["task_id"] == task_id
    assert page.json()["items"][0]["batch_outcome_code"] is None
    assert page.json()["items"][0]["exception_types"] == []
    detail = client[0].get(f"/api/collection-batches/{task_id}")
    assert detail.status_code == 200
    assert detail.json()["batch_id"] == batch_id
    assert detail.json()["planned_products"] == 1
    assert len(detail.json()["items"]) == 1
    assert detail.json()["items"][0]["base_status"] is None
    assert detail.json()["items"][0]["deletion_notice"] is None
    assert detail.json()["items"][0]["attempts"] == []


def test_live_batch_status_keeps_runtime_outcome_and_adds_persistence_state(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    body = client[0].get("/api/competitors/collect-batch/status").json()
    assert body["outcome_code"] == "success"
    assert body["lifecycle_status"] in {None, "created", "running", "terminal"}
    assert body["batch_outcome_code"] is None


def test_live_batch_status_includes_current_product_title(
    client: tuple[TestClient, sessionmaker[Session]], monkeypatch: pytest.MonkeyPatch,
) -> None:
    competitor_id = add_competitor(client[1], 1)
    with client[1]() as db:
        product = db.get(Competitor, competitor_id)
        assert product is not None
        product.title = "当前采集商品"
        db.commit()
    runtime = BatchRuntime()
    assert runtime.reserve([competitor_id])
    runtime.set_current(competitor_id)
    monkeypatch.setattr(competitors_module, "BATCH_RUNTIME", runtime)

    response = client[0].get("/api/competitors/collect-batch/status")

    assert response.status_code == 200
    assert response.json()["current_competitor_title"] == "当前采集商品"
    runtime.finish("success")


def test_persisted_attempt_records_navigation_and_observations_once(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    competitor_id = add_competitor(client[1], 1)
    runtime = BatchRuntime()
    runtime.reserve([competitor_id])
    with client[1]() as db:
        batch = create_collection_batch(db, [competitor_id], BatchConfig(), trigger_kind="manual_selected")
        batch_id = batch.id
    with client[1]() as db:
        item = db.query(CollectionBatchItem).filter_by(batch_id=batch_id).one()
        item_id = item.id
    metrics = [OperatingMetricData(
        metric_key=key, status="source_unavailable" if index == 0 else "placeholder",
        raw_value=None if index == 0 else "-", source="assistant", offer_id="1000000000001",
        observed_at=datetime.now(timezone.utc), reason="助手标题不存在或不唯一" if index == 0 else None,
    ) for index, key in enumerate(("listing_time", "monthly_deal", "monthly_dropship", "annual_units", "annual_orders", "review_count", "positive_rate", "pickup_rate"))]

    def page_result(_url: str, offer_id: str, **callbacks: object) -> CollectionPageResult:
        callbacks["on_navigation_claim"]()
        callbacks["on_navigation_confirmed"]()
        return CollectionPageResult(offer_id, _collected_product(offer_id), None, metrics)

    with patch.object(collection_service, "collect_1688_product", side_effect=page_result):
        with client[1]() as db:
            result = collection_service.collect_competitor(
                db, competitor_id, batch_item_id=item_id, attempt_number=1,
                attempt_kind="first_pass", batch_runtime=runtime,
                batch_reservation=runtime.reservation_token(),
                on_attempt_started=runtime.record_attempt_started,
                on_external_access=runtime.record_external_access,
            )

    with client[1]() as db:
        run = db.query(CollectionRun).one()
        item = db.get(CollectionBatchItem, item_id)
        assert result.collection_run.id == run.id
        assert (run.attempt_number, run.attempt_kind) == (1, "first_pass")
        assert run.navigation_claimed_at is not None and run.navigation_confirmed_at is not None
        assert db.query(OperatingMetricObservation).filter_by(collection_run_id=run.id).count() == 8
        assert (item.attempts_started, item.page_visits, item.retry_visits) == (1, 1, 0)
        item.final_result = "final_failed"
        item.execution_status = "completed"
        item.base_result = "success"
        batch = db.get(CollectionBatch, batch_id)
        assert batch is not None
        batch.lifecycle_status = "terminal"
        batch.outcome_code = "partial_success"
        db.commit()
    assert (runtime.snapshot()["attempts_started"], runtime.snapshot()["page_visits"]) == (1, 1)
    assert client[0].delete(f"/api/competitors/{competitor_id}").status_code == 204
    page = client[0].get("/api/collection-batches?anomaly=source_unavailable")
    assert page.status_code == 200 and page.json()["total"] == 1
    detail = client[0].get(f"/api/collection-batches/{batch.task_id}").json()
    item = detail["items"][0]
    assert item["identity_removed"] is True
    assert item["source_unavailable_count"] == 1
    assert item["attempts"] == []


@pytest.mark.parametrize("mode", ["retry_recovers", "circuit_breaker", "verification_during_retry", "verification_retry_slot", "verification_limit", "save_failure", "retry_offline", "circuit_loading_gap", "retry_base_failure"])
def test_persisted_retry_recovery_and_three_item_circuit_breaker(
    client: tuple[TestClient, sessionmaker[Session]], mode: str,
) -> None:
    competitor_ids = [add_competitor(client[1], index) for index in range(1, 5 if mode == "circuit_loading_gap" else 4 if mode == "circuit_breaker" else 3 if mode.startswith("verification") else 2)]
    runtime = BatchRuntime()
    config = _test_config(
        item_interval_seconds=0, batch_rest_seconds=0, verification_cooldown_seconds=0,
        auto_resume_max=1 if mode in {"verification_during_retry", "verification_retry_slot"} else 0,
        operating_metrics_retry_max=2 if mode == "verification_retry_slot" else 1,
    )
    runtime.reserve(competitor_ids, config)
    with client[1]() as db:
        batch = create_collection_batch(db, competitor_ids, config, trigger_kind="manual_selected")
        batch_id = batch.id
        runtime.bind_batch(batch)
    calls: list[tuple[int, str]] = []
    keys = ("listing_time", "monthly_deal", "monthly_dropship", "annual_units", "annual_orders", "review_count", "positive_rate", "pickup_rate")

    def collect(db: Session, competitor_id: int, *, batch_item_id: int, attempt_number: int, attempt_kind: str, on_attempt_started: object, on_external_access: object, **_kwargs: object) -> SimpleNamespace:
        calls.append((competitor_id, attempt_kind))
        if mode == "save_failure":
            raise CollectionError("collection_save_failed", "采集结果保存失败")
        now = datetime.now(timezone.utc)
        first_pass = attempt_kind == "first_pass"
        all_unavailable = first_pass and (mode == "circuit_breaker" or (mode == "circuit_loading_gap" and competitor_id != competitor_ids[2]))
        metrics = [OperatingMetricData(
            metric_key=key,
            status="source_unavailable" if all_unavailable or (first_pass and index == 0) or (mode == "verification_retry_slot" and attempt_kind == "verification_resume" and index == 0) else "observed",
            raw_value=None if all_unavailable or (first_pass and index == 0) or (mode == "verification_retry_slot" and attempt_kind == "verification_resume" and index == 0) else "1",
            source="assistant", offer_id=f"{1000000000000 + competitor_id}", observed_at=now,
            reason="助手标题不存在或不唯一" if all_unavailable or (first_pass and index == 0) or (mode == "verification_retry_slot" and attempt_kind == "verification_resume" and index == 0) else None,
        ) for index, key in enumerate(keys)]
        if mode == "circuit_loading_gap" and competitor_id == competitor_ids[2]:
            metrics = [OperatingMetricData(key, "loading", None, "assistant", f"{1000000000000 + competitor_id}", now, "字段仍在加载") for key in keys]
        if mode in {"retry_offline", "retry_base_failure"} and not first_pass:
            metrics = []
        run = CollectionRun(
            competitor_id=competitor_id, collection_batch_item_id=batch_item_id,
            attempt_number=attempt_number, attempt_kind=attempt_kind, started_at=now,
            finished_at=now, status="success", operating_metrics_status="failed" if all_unavailable or first_pass else "success",
            navigation_claimed_at=now, navigation_confirmed_at=now,
        )
        db.add(run)
        if mode == "retry_base_failure" and not first_pass:
            run.status = "failed"
            run.operating_metrics_status = "not_attempted"
            run.error_type = "collection_timeout"
        if mode.startswith("verification") and competitor_id == competitor_ids[0] and attempt_kind == "operating_metrics_retry" and not (mode == "verification_retry_slot" and calls.count((competitor_id, attempt_kind)) > 1):
            run.status = "failed"
            run.operating_metrics_status = "blocked"
            run.error_type = "1688_verification_required"
        db.flush()
        item = db.get(CollectionBatchItem, batch_item_id)
        assert item is not None
        item.attempts_started += 1
        item.page_visits += 1
        if attempt_kind == "operating_metrics_retry":
            item.retry_visits += 1
        elif attempt_kind == "verification_resume":
            item.verification_resume_visits += 1
        db.add_all([OperatingMetricObservation(
            competitor_id=competitor_id, collection_run_id=run.id, platform="1688",
            offer_id=f"{1000000000000 + competitor_id}", metric_key=metric.metric_key,
            status=metric.status, raw_value=metric.raw_value, source=metric.source,
            observed_at=metric.observed_at, reason=metric.reason,
        ) for metric in metrics])
        db.commit()
        on_attempt_started()
        on_external_access()
        if mode == "retry_base_failure" and not first_pass:
            raise CollectionError("collection_timeout", "页面加载超时", operating_metrics_status="not_attempted")
        if mode.startswith("verification") and competitor_id == competitor_ids[0] and attempt_kind == "operating_metrics_retry" and not (mode == "verification_retry_slot" and calls.count((competitor_id, attempt_kind)) > 1):
            raise CollectionError("1688_verification_required", "需要人工验证", operating_metrics_status="blocked")
        return SimpleNamespace(
            outcome="offline" if mode == "retry_offline" and not first_pass else "active", operating_metrics_status="failed" if all_unavailable or first_pass else "success",
            operating_metric_data=metrics,
        )

    context = FakeContext()
    def restore_retry_verification(_context: FakeContext, _page: object) -> None:
        context.pages.clear()
        if mode == "verification_limit":
            runtime.request_end()
    with patch.object(collection_service, "sync_playwright", return_value=FakePlaywright(context)), \
        patch.object(collection_service, "move_context_offscreen"), \
        patch.object(collection_service, "restore_context_window", side_effect=restore_retry_verification), \
        patch.object(collection_service, "collect_competitor", side_effect=collect):
        run_batch_collection(client[1], competitor_ids, runtime, config=config, persisted_batch_id=batch_id)

    with client[1]() as db:
        batch = db.get(CollectionBatch, batch_id)
        items = db.query(CollectionBatchItem).filter_by(batch_id=batch_id).order_by(CollectionBatchItem.position).all()
        assert batch is not None and batch.lifecycle_status == "terminal"
        if mode == "retry_recovers":
            assert calls == [(competitor_ids[0], "first_pass"), (competitor_ids[0], "operating_metrics_retry")]
            assert items[0].final_result == "retry_success"
            assert (items[0].attempts_started, items[0].page_visits, items[0].retry_visits) == (2, 2, 1)
            assert items[0].technical_exception_count == 1
            assert batch.outcome_code == "success"
        elif mode == "retry_base_failure":
            assert calls == [(competitor_ids[0], "first_pass"), (competitor_ids[0], "operating_metrics_retry")]
            assert items[0].base_result == "failed"
            assert items[0].final_result == "final_failed"
            assert batch.outcome_code == "collect_failed"
            assert runtime.snapshot()["failed"] == 1
            summary = client[0].get("/api/collection-batches").json()["items"][0]
            assert summary["base_failed_products"] == 1
            assert client[0].get("/api/collection-batches?anomaly=base_failed").json()["total"] == 1
        elif mode == "retry_offline":
            assert calls == [(competitor_ids[0], "first_pass"), (competitor_ids[0], "operating_metrics_retry")]
            assert items[0].final_result == "final_failed"
            assert items[0].technical_exception_count == 1
            assert batch.outcome_code == "partial_success"
        elif mode == "circuit_loading_gap":
            assert all(kind == "first_pass" for _, kind in calls)
            assert len(calls) == 4
            assert batch.circuit_breaker_streak == 3
            assert batch.circuit_breaker_cancelled == 4
        elif mode == "circuit_breaker":
            assert all(kind == "first_pass" for _, kind in calls)
            assert batch.circuit_breaker_cancelled == 3
            assert all(item.cancelled_retry_count == 1 and item.stop_reason == "source_unavailable_circuit_breaker" for item in items)
        elif mode == "verification_during_retry":
            assert calls == [(competitor_ids[0], "first_pass"), (competitor_ids[1], "first_pass"), (competitor_ids[0], "operating_metrics_retry"), (competitor_ids[0], "verification_resume"), (competitor_ids[1], "operating_metrics_retry")]
            assert items[0].final_result == "verification_resume_success"
            assert (items[0].attempts_started, items[0].page_visits, items[0].retry_visits, items[0].verification_resume_visits) == (3, 3, 1, 1)
            assert batch.outcome_code == "success"
            assert runtime.snapshot()["auto_resume_attempt"] == 1
        elif mode == "verification_retry_slot":
            assert calls == [(competitor_ids[0], "first_pass"), (competitor_ids[1], "first_pass"), (competitor_ids[0], "operating_metrics_retry"), (competitor_ids[0], "verification_resume"), (competitor_ids[0], "operating_metrics_retry"), (competitor_ids[1], "operating_metrics_retry")]
            assert items[0].final_result == "retry_success"
            assert (items[0].attempts_started, items[0].page_visits, items[0].retry_visits, items[0].verification_resume_visits) == (4, 4, 2, 1)
            assert batch.outcome_code == "success"
        elif mode == "verification_limit":
            assert calls == [(competitor_ids[0], "first_pass"), (competitor_ids[1], "first_pass"), (competitor_ids[0], "operating_metrics_retry")]
            assert items[0].final_result == "final_failed" and items[0].protection_reason == "1688_verification_required"
            assert items[1].final_result == "final_failed"
            assert items[1].retry_visits == 0
            assert batch.outcome_code == "verification_required"
            assert runtime.snapshot()["status"] == "stopped"
        else:
            assert calls == [(competitor_ids[0], "first_pass")]
            assert batch.outcome_code == "infrastructure_error"


def test_restart_before_navigation_is_not_executed(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    competitor_id = add_competitor(client[1], 1)
    with client[1]() as db:
        batch = create_collection_batch(db, [competitor_id], _test_config(), trigger_kind="manual_selected")
        item = db.query(CollectionBatchItem).filter_by(batch_id=batch.id).one()
        item.attempts_started = 1
        db.add(CollectionRun(
            competitor_id=competitor_id, collection_batch_item_id=item.id, attempt_number=1,
            attempt_kind="first_pass", started_at=datetime.now(timezone.utc), status="running",
        ))
        db.commit()
        batch_id = batch.id
    assert recover_interrupted_batches(client[1]) == 1
    with client[1]() as db:
        batch = db.get(CollectionBatch, batch_id)
        item = db.query(CollectionBatchItem).filter_by(batch_id=batch_id).one()
        run = db.query(CollectionRun).filter_by(collection_batch_item_id=item.id).one()
        assert run.navigation_terminal_reason == "interrupted_before_navigation"
        assert item.final_result == "not_executed" and item.execution_status == "not_executed" and item.base_result is None
        assert batch is not None and batch.outcome_code == "interrupted"


def test_collect_competitor_forwards_metrics_stop_callback(client):
    competitor_id = add_competitor(client[1], 1)
    stop = lambda: True
    received = []

    def collector(_url, offer_id, *, stop_waiting_for_metrics=None, **_callbacks):
        received.append(stop_waiting_for_metrics)
        return CollectionPageResult(offer_id, _collected_product(offer_id), None, [
            OperatingMetricData(key, "placeholder", "-", "assistant", offer_id, datetime.now(timezone.utc), None)
            for key in ("listing_time", "monthly_deal", "monthly_dropship", "annual_units", "annual_orders", "review_count", "positive_rate", "pickup_rate")
        ])

    with patch.object(collection_service, "collect_1688_product", collector):
        with client[1]() as db:
            collection_service.collect_competitor(db, competitor_id, stop_waiting_for_metrics=stop)
    assert received == [stop]


def test_finalizer_failure_still_releases_batch_lock(client):
    competitor_id = add_competitor(client[1], 1)
    runtime = BatchRuntime()
    config = _test_config(item_interval_seconds=0)
    runtime.reserve([competitor_id], config)
    with client[1]() as db:
        batch = create_collection_batch(db, [competitor_id], config, trigger_kind="manual_selected")
        batch_id = batch.id
    with patch.object(collection_service, "sync_playwright", return_value=FakePlaywright(FakeContext())), \
        patch.object(collection_service, "move_context_offscreen"), \
        patch.object(collection_service, "collect_competitor", side_effect=CollectionError("collection_save_failed", "save failed")), \
        patch.object(collection_service, "_finalize_persisted_batch", side_effect=RuntimeError("persist error")):
        with pytest.raises(RuntimeError, match="persist error"):
            run_batch_collection(client[1], [competitor_id], runtime, config=config, persisted_batch_id=batch_id)
    acquired = COLLECTION_LOCK.acquire(blocking=False)
    COLLECTION_LOCK.release()
    assert acquired
    assert runtime.snapshot()["phase"] is None


def test_first_pass_verification_resume_preserves_attempt_and_visit_kind(client):
    competitor_id = add_competitor(client[1], 1)
    runtime = BatchRuntime()
    config = _test_config(item_interval_seconds=0, verification_cooldown_seconds=0, auto_resume_max=1)
    runtime.reserve([competitor_id], config)
    with client[1]() as db:
        batch = create_collection_batch(db, [competitor_id], config, trigger_kind="manual_selected")
        batch_id = batch.id
    calls = []

    def collector(_url, offer_id, **kwargs):
        kwargs["on_navigation_claim"]()
        kwargs["on_navigation_confirmed"]()
        calls.append(offer_id)
        if len(calls) == 1:
            raise collection_service.VerificationRequiredError()
        return CollectionPageResult(offer_id, _collected_product(offer_id), None, [
            OperatingMetricData(key, "placeholder", "-", "assistant", offer_id, datetime.now(timezone.utc), None)
            for key in ("listing_time", "monthly_deal", "monthly_dropship", "annual_units", "annual_orders", "review_count", "positive_rate", "pickup_rate")
        ])

    with patch.object(collection_service, "sync_playwright", return_value=FakePlaywright(FakeContext())), \
        patch.object(collection_service, "move_context_offscreen"), \
        patch.object(collection_service, "collect_1688_product", collector):
        run_batch_collection(client[1], [competitor_id], runtime, config=config, persisted_batch_id=batch_id)
    with client[1]() as db:
        runs = db.query(CollectionRun).order_by(CollectionRun.id).all()
        item = db.query(CollectionBatchItem).filter_by(batch_id=batch_id).one()
        assert [run.attempt_kind for run in runs] == ["first_pass", "verification_resume"]
        assert (item.page_visits, item.verification_resume_visits, item.retry_visits) == (2, 1, 0)
        assert item.final_result == "verification_resume_success"


def test_verification_outcome_precedes_user_end(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    competitor_id = add_competitor(client[1], 1)
    with client[1]() as db:
        batch = create_collection_batch(db, [competitor_id], _test_config(), trigger_kind="manual_selected")
        item = db.query(CollectionBatchItem).filter_by(batch_id=batch.id).one()
        item.final_result = "verification_required"
        item.execution_status = "completed"
        db.commit()
        batch_id = batch.id
    runtime = BatchRuntime()
    runtime.reserve([competitor_id], _test_config())
    runtime.runner_active = True
    runtime.mark_verification()
    assert runtime.request_end()
    _finalize_persisted_batch(client[1], batch_id, runtime)
    with client[1]() as db:
        batch = db.get(CollectionBatch, batch_id)
        assert batch is not None and batch.outcome_code == "verification_required"


def test_runner_dispatch_failure_closes_created_batch(client: tuple[TestClient, sessionmaker[Session]]) -> None:
    competitor_id = add_competitor(client[1], 1)
    with client[1]() as db, patch.object(competitors_module, "start_batch_task", side_effect=RuntimeError("runner dispatch failed")):
        with pytest.raises(RuntimeError, match="runner dispatch failed"):
            asyncio.run(competitors_module.collect_batch(
                competitors_module.CollectBatchRequest(mode="selected", competitor_ids=[competitor_id]), db,
            ))
    with client[1]() as db:
        batch = db.query(CollectionBatch).one()
        item = db.query(CollectionBatchItem).filter_by(batch_id=batch.id).one()
        assert (batch.lifecycle_status, batch.outcome_code, batch.protection_reason) == (
            "terminal", "infrastructure_error", "runner_start_failed",
        )
        assert (item.final_result, item.execution_status) == ("not_executed", "not_executed")


def test_restart_terminal_run_rebuilds_exception_counts(client):
    competitor_id = add_competitor(client[1], 1)
    now = datetime.now(timezone.utc)
    with client[1]() as db:
        batch = create_collection_batch(db, [competitor_id], _test_config(), trigger_kind="manual_selected")
        batch.lifecycle_status = "running"
        item = db.query(CollectionBatchItem).filter_by(batch_id=batch.id).one()
        item.attempts_started = item.page_visits = 1
        run = CollectionRun(competitor_id=competitor_id, collection_batch_item_id=item.id,
                            attempt_number=1, attempt_kind="first_pass", started_at=now,
                            finished_at=now, status="success", operating_metrics_status="failed")
        db.add(run)
        db.flush()
        db.add_all([OperatingMetricObservation(competitor_id=competitor_id, collection_run_id=run.id,
            platform="1688", offer_id=str(1000000000000 + competitor_id), metric_key=key,
            status="source_unavailable", source="assistant", observed_at=now,
            reason="助手标题不存在或不唯一") for key in
            ("listing_time", "monthly_deal", "monthly_dropship", "annual_units", "annual_orders", "review_count", "positive_rate", "pickup_rate")])
        db.commit()
        batch_id = batch.id
    assert recover_interrupted_batches(client[1]) == 1
    assert recover_interrupted_batches(client[1]) == 0
    with client[1]() as db:
        item = db.query(CollectionBatchItem).filter_by(batch_id=batch_id).one()
        assert item.final_result == "final_failed"
        assert item.technical_exception_count == item.source_unavailable_count == 8
        response = client[0].get("/api/collection-batches").json()["items"][0]
        assert response["technical_exception_products"] == 1
        assert response["exception_types"] == ["source_unavailable"]
