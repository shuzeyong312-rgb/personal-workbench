from collections.abc import Generator
from datetime import datetime, timezone
from decimal import Decimal
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
    run_batch_collection,
)
import app.collection.service as collection_service
import app.competitors as competitors_module
from app.collection.daily import run_daily_collection_cycle
from app.database import get_db
from app.main import app
from app.collection.types import ProductData
from app.models import Base, Competitor, ProductSnapshot
from app.settings import update_competitor_monitoring_setting


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

        def commit() -> None:
            nonlocal commits
            commits += 1
            if commits == 2:
                raise RuntimeError("save failed")
            original_commit()

        def external_collector(*_args: object, **_kwargs: object) -> ProductData:
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
    daily_collect = Mock()
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
        daily = run_daily_collection_cycle(client[1], collect=daily_collect)
        delete_batch = client[0].post(
            "/api/competitors/delete-batch",
            json={"competitor_ids": [1]},
        )

        assert second_batch.status_code == 409
        assert second_batch.json()["code"] == "collection_in_progress"
        assert single.status_code == 409
        assert single.json()["code"] == "collection_in_progress"
        assert daily.interrupted == 1
        daily_collect.assert_not_called()
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
    }
    values.update(overrides)
    return BatchConfig(**values)


def test_batch_start_freezes_one_settings_snapshot_and_the_next_start_uses_the_new_one(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    add_competitor(client[1], 1)
    old = {"item_interval_seconds": 1, "continuous_collection_count": 1, "batch_rest_seconds": 0, "verification_cooldown_seconds": 60, "auto_resume_max": 0}
    new = {"item_interval_seconds": 60, "continuous_collection_count": 50, "batch_rest_seconds": 1800, "verification_cooldown_seconds": 3600, "auto_resume_max": 5}
    assert client[0].put("/api/settings/competitor-monitoring", json=old).status_code == 200
    with patch("app.competitors.start_batch_task") as start:
        assert client[0].post("/api/competitors/collect-batch", json={"mode": "selected", "competitor_ids": [1]}).status_code == 202
        frozen = start.call_args.kwargs["config"]
        with client[1]() as settings_db:
            assert update_competitor_monitoring_setting(new, db=settings_db) == new
        assert frozen == BatchConfig(**old)
        BATCH_RUNTIME.finish("success")
        assert client[0].post("/api/competitors/collect-batch", json={"mode": "selected", "competitor_ids": [1]}).status_code == 202

    assert start.call_args.kwargs["config"] == BatchConfig(**new)


def test_batch_start_and_settings_put_interleaving_freeze_only_complete_old_or_new_configurations(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    add_competitor(client[1], 1)
    old = {"item_interval_seconds": 1, "continuous_collection_count": 1, "batch_rest_seconds": 0, "verification_cooldown_seconds": 60, "auto_resume_max": 0}
    new = {"item_interval_seconds": 60, "continuous_collection_count": 50, "batch_rest_seconds": 1800, "verification_cooldown_seconds": 3600, "auto_resume_max": 5}
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
        assert start.call_args.kwargs["config"] == BatchConfig(**old)

    BATCH_RUNTIME.finish("success")
    with patch("app.competitors.start_batch_task") as next_start:
        assert client[0].post("/api/competitors/collect-batch", json={"mode": "selected", "competitor_ids": [1]}).status_code == 202
    assert next_start.call_args.kwargs["config"] == BatchConfig(**new)


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
