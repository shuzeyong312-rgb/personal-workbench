import asyncio
import inspect
from dataclasses import dataclass, field
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from math import ceil
from threading import Event, Lock, RLock
from time import monotonic
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.collection.collector_1688 import (
    CollectionTimeoutError,
    LoginRequiredError,
    OfflineProductDetected,
    PageUnavailableError,
    VerificationRequiredError,
    collect_1688_product,
    move_context_offscreen,
    restore_context_window,
    sync_playwright,
    _close_quietly,
    _launch_context,
)
from app.collection.parser_1688 import (
    CollectionParseError,
    OfferIdMismatchError,
    normalize_main_image_url,
)
from app.collection.types import CollectionPageResult, OperatingMetricData, ProductData, SkuData
from app.changes import detect_changes
from app.models import ChangeEvent, CollectionBatch, CollectionBatchItem, CollectionRun, Competitor, OperatingMetricObservation, ProductSnapshot, SkuSnapshot
from app.ownership import apply_collected_ownership
from app.settings import competitor_monitoring_defaults


COLLECTION_LOCK = RLock()


def _monitoring_default(field_name: str) -> int:
    """Keep runner compatibility defaults sourced at the Settings boundary."""
    return int(competitor_monitoring_defaults()[field_name])


@dataclass(frozen=True)
class BatchConfig:
    item_interval_seconds: int = field(default_factory=lambda: _monitoring_default("item_interval_seconds"))
    continuous_collection_count: int = field(default_factory=lambda: _monitoring_default("continuous_collection_count"))
    batch_rest_seconds: int = field(default_factory=lambda: _monitoring_default("batch_rest_seconds"))
    verification_cooldown_seconds: int = field(default_factory=lambda: _monitoring_default("verification_cooldown_seconds"))
    auto_resume_max: int = field(default_factory=lambda: _monitoring_default("auto_resume_max"))
    operating_metrics_retry_max: int = field(default_factory=lambda: _monitoring_default("operating_metrics_retry_max"))


@dataclass(frozen=True)
class BatchItemResult:
    competitor_id: int
    status: str
    error_code: str | None = None
    message: str | None = None
    outcome: str | None = None
    operating_metrics_status: str = "not_attempted"


class BatchRuntime:
    """The one in-process batch state exposed by the polling endpoint."""

    def __init__(self) -> None:
        self._lock = Lock()
        self.admissions: dict[str, dict[str, object]] = {}
        self.work_kind = "collect_products"
        self.current_input_position: int | None = None
        self.input_progress: dict[str, int | None] | None = None
        self.status = "idle"
        self.outcome_code: str | None = None
        self.total = 0
        self.completed = 0
        self.succeeded = 0
        self.failed = 0
        self.verification_required = 0
        self.operating_metrics_counts = {key: 0 for key in ("not_attempted", "success", "partial", "no_values", "failed", "blocked")}
        self.current_competitor_id: int | None = None
        self.browser_open = False
        self.runner_active = False
        self.auto_resume_attempt = 0
        self.auto_resume_max = BatchConfig().auto_resume_max
        self.cooldown_remaining_seconds = 0
        self.resting_remaining_seconds = 0
        self.external_access_count = 0
        self.items: list[BatchItemResult] = []
        self.batch_id: int | None = None
        self.task_id: str | None = None
        self.lifecycle_status: str | None = None
        self.batch_outcome_code: str | None = None
        self.phase: str | None = None
        self.attempts_started = 0
        self.page_visits = 0
        self.page_visits_unknown = 0
        self.verification_resume_visits = 0
        self.retry_visits = 0
        self.retry_total = 0
        self.retry_completed = 0
        self.operating_metrics_retry_max = 0
        self.stop_event = Event()
        self.resume_event = Event()
        self.resume_event.set()
        self._paused_status: str | None = None
        self._end_requested = False
        self.task: asyncio.Task[Any] | None = None
        self._reservation_sequence = 0
        self._active_reservation: int | None = None

    def is_busy(self) -> bool:
        with self._lock:
            return self.runner_active or self.browser_open

    def reserve(self, competitor_ids: list[int] | None, config: BatchConfig | None = None, *, input_positions: list[int] | None = None) -> bool:
        with self._lock:
            if self.runner_active or self.browser_open:
                return False
            self._reservation_sequence += 1
            self._active_reservation = self._reservation_sequence
            self.status = "running"
            self.outcome_code = None
            self.work_kind = "add_links" if input_positions is not None else "collect_products"
            self.current_input_position = None
            self.input_progress = ({"total": len(input_positions), "candidate_total": None, "processed": 0, "pending": len(input_positions), "remaining": len(input_positions), **{key: 0 for key in ("added", "business_rejected", "technical_failed", "verification_required", "interrupted", "not_executed")}} if input_positions is not None else None)
            self.total = len(competitor_ids or [])
            self.completed = 0
            self.succeeded = 0
            self.failed = 0
            self.verification_required = 0
            self.operating_metrics_counts = {key: 0 for key in self.operating_metrics_counts}
            self.current_competitor_id = None
            self.browser_open = False
            self.runner_active = True
            self.auto_resume_attempt = 0
            self.auto_resume_max = (config or BatchConfig()).auto_resume_max
            self.cooldown_remaining_seconds = 0
            self.resting_remaining_seconds = 0
            self.external_access_count = 0
            self.items = []
            self.batch_id = None
            self.task_id = None
            self.lifecycle_status = None
            self.batch_outcome_code = None
            self.phase = None if self.work_kind == "add_links" else "first_pass"
            self.attempts_started = 0
            self.page_visits = 0
            self.page_visits_unknown = 0
            self.verification_resume_visits = 0
            self.retry_visits = 0
            self.retry_total = 0
            self.retry_completed = 0
            self.operating_metrics_retry_max = 0 if self.work_kind == "add_links" else (config or BatchConfig()).operating_metrics_retry_max
            self.stop_event = Event()
            self.resume_event = Event()
            self.resume_event.set()
            self._paused_status = None
            self._end_requested = False
            self.task = None
            return True

    def reserve_add(self, positions: list[int], config: BatchConfig) -> bool:
        return self.reserve(None, config, input_positions=positions)

    def set_input_progress(self, summary: dict[str, int | None]) -> None:
        with self._lock:
            self.input_progress = dict(summary)

    def set_current_input(self, position: int | None) -> None:
        with self._lock:
            self.current_input_position = position

    def reservation_token(self) -> int | None:
        with self._lock:
            return self._active_reservation

    def owns_reservation(self, token: int | None) -> bool:
        with self._lock:
            return token is not None and token == self._active_reservation and self.runner_active

    def attach_task(self, task: asyncio.Task[Any]) -> None:
        with self._lock:
            self.task = task

    def get_task(self) -> asyncio.Task[Any] | None:
        with self._lock:
            return self.task

    def set_browser_open(self, value: bool) -> None:
        with self._lock:
            self.browser_open = value

    def set_running(self) -> bool:
        with self._lock:
            if self.stop_event.is_set() or not self.resume_event.is_set():
                return False
            self.status = "running"
            self.cooldown_remaining_seconds = 0
            self.resting_remaining_seconds = 0
            self._paused_status = None
            return True

    def begin_auto_resume(self) -> None:
        with self._lock:
            self.auto_resume_attempt += 1

    def enter_cooldown(self, seconds: float) -> None:
        with self._lock:
            if self.stop_event.is_set():
                return
            if self.resume_event.is_set():
                self.status = "cooling_down"
            else:
                self._paused_status = "cooling_down"
                self.status = "paused"
            self.cooldown_remaining_seconds = max(0, ceil(seconds))
            self.resting_remaining_seconds = 0

    def enter_resting(self, seconds: float) -> None:
        with self._lock:
            if self.stop_event.is_set():
                return
            if self.resume_event.is_set():
                self.status = "resting"
            else:
                self._paused_status = "resting"
                self.status = "paused"
            self.resting_remaining_seconds = max(0, ceil(seconds))
            self.cooldown_remaining_seconds = 0

    def wait_for_cooldown(self, seconds: float) -> bool:
        return self._wait_with_remaining(seconds, "cooldown_remaining_seconds")

    def wait_for_resting(self, seconds: float, on_pause=None) -> bool:
        return self._wait_with_remaining(seconds, "resting_remaining_seconds", on_pause=on_pause)

    def _wait_with_remaining(self, seconds: float, field: str, on_pause=None) -> bool:
        remaining = max(0, seconds)
        while True:
            with self._lock:
                stop_event = self.stop_event
                stopped = stop_event.is_set()
                paused = not self.resume_event.is_set()
                if remaining <= 0 and not stopped and not paused:
                    setattr(self, field, 0)
                    self.status = "running"
                    self.cooldown_remaining_seconds = 0
                    self.resting_remaining_seconds = 0
                    self._paused_status = None
                    return True
                setattr(self, field, max(0, ceil(remaining)))
            if stopped:
                with self._lock:
                    setattr(self, field, 0)
                return False
            if paused:
                if on_pause is not None and not on_pause():
                    with self._lock:
                        setattr(self, field, 0)
                    return False
                if not self.wait_for_resume():
                    with self._lock:
                        setattr(self, field, 0)
                    return False
                continue
            started = monotonic()
            if self.wait_for_stop(min(remaining, 0.1)):
                with self._lock:
                    setattr(self, field, 0)
                return False
            if not self.pause_requested():
                remaining = max(0, remaining - (monotonic() - started))

    def record_external_access(self) -> None:
        with self._lock:
            self.external_access_count += 1

    def bind_batch(self, batch: CollectionBatch) -> None:
        with self._lock:
            self.batch_id = batch.id
            self.task_id = batch.task_id
            self.lifecycle_status = batch.lifecycle_status
            self.batch_outcome_code = batch.outcome_code

    def set_persisted_batch_state(self, lifecycle_status: str, outcome_code: str | None = None) -> None:
        with self._lock:
            self.lifecycle_status = lifecycle_status
            self.batch_outcome_code = outcome_code

    def record_attempt_started(self) -> None:
        with self._lock:
            self.attempts_started += 1

    def record_page_visit(self, attempt_kind: str | None) -> None:
        with self._lock:
            self.page_visits += 1
            if attempt_kind == "verification_resume":
                self.verification_resume_visits += 1
            elif attempt_kind == "operating_metrics_retry":
                self.retry_visits += 1

    def set_phase(self, phase: str | None) -> None:
        with self._lock:
            self.phase = phase

    def set_retry_total(self, total: int) -> None:
        with self._lock:
            self.retry_total = total

    def record_retry_completed(self) -> None:
        with self._lock:
            self.retry_completed += 1

    def external_accesses(self) -> int:
        with self._lock:
            return self.external_access_count

    def set_current(self, competitor_id: int | None) -> None:
        with self._lock:
            self.current_competitor_id = competitor_id

    def record(self, result: BatchItemResult) -> None:
        with self._lock:
            self.items.append(result)
            self.completed += 1
            if result.status == "success":
                self.succeeded += 1
            elif result.status == "verification_required":
                self.verification_required += 1
            else:
                self.failed += 1
            self.operating_metrics_counts[result.operating_metrics_status] += 1

    def finish(self, outcome_code: str, *, status: str = "completed") -> None:
        with self._lock:
            self.status = status
            self.outcome_code = outcome_code
            self.current_competitor_id = None
            self.current_input_position = None
            self.runner_active = False
            self._active_reservation = None
            self.cooldown_remaining_seconds = 0
            self.resting_remaining_seconds = 0
            self._paused_status = None
            self.resume_event.set()

    def mark_verification(self) -> None:
        with self._lock:
            if self.stop_event.is_set():
                return
            self.status = "verification_required"
            self.outcome_code = "verification_required"
            self.resume_event.set()

    def is_running(self) -> bool:
        with self._lock:
            return self.status in {"running", "resting"}

    def has_failures(self) -> bool:
        with self._lock:
            return self.failed > 0

    def mark_runner_stopped(self) -> None:
        with self._lock:
            self.runner_active = False
            self._active_reservation = None
            self.browser_open = False
            self.cooldown_remaining_seconds = 0
            self.resting_remaining_seconds = 0

    def request_stop(self) -> None:
        with self._lock:
            self.stop_event.set()
            self.resume_event.set()

    def request_end(self) -> bool:
        with self._lock:
            if not self.runner_active or self.status not in {"running", "pausing", "paused", "resting", "cooling_down", "verification_required"}:
                return False
            self._end_requested = True
            self.status = "stopping"
            self.stop_event.set()
            self.resume_event.set()
            return True

    def end_requested(self) -> bool:
        with self._lock:
            return self._end_requested

    def request_pause(self) -> bool:
        with self._lock:
            if not self.runner_active or self.stop_event.is_set() or self.status not in {"running", "resting", "cooling_down"}:
                return False
            was_collecting = self.status == "running" and (self.current_competitor_id is not None or self.current_input_position is not None)
            self._paused_status = self.status
            self.resume_event.clear()
            self.status = "pausing" if was_collecting else "paused"
            return True

    def resume(self) -> bool:
        with self._lock:
            if not self.runner_active or self.status not in {"paused", "pausing"}:
                return False
            self.status = self._paused_status or "running"
            self._paused_status = None
            self.resume_event.set()
            return True

    def pause_requested(self) -> bool:
        return not self.resume_event.is_set()

    def mark_paused(self) -> None:
        with self._lock:
            if self.stop_event.is_set() or self.resume_event.is_set():
                return
            self.status = "paused"
            self.current_competitor_id = None

    def wait_for_resume(self) -> bool:
        while not self.resume_event.wait(0.1):
            if self.stop_requested():
                return False
        return not self.stop_requested()

    def stop_requested(self) -> bool:
        with self._lock:
            return self.stop_event.is_set()

    def wait_for_stop(self, timeout: float) -> bool:
        deadline = monotonic() + max(0, timeout)
        while True:
            with self._lock:
                stop_event = self.stop_event
                resume_event = self.resume_event
            if stop_event.is_set():
                return True
            if not resume_event.is_set():
                return False
            remaining = deadline - monotonic()
            if remaining <= 0:
                return False
            stop_event.wait(min(remaining, 0.1))

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "work_kind": self.work_kind,
                "current_input_position": self.current_input_position,
                "input_progress": dict(self.input_progress) if self.input_progress is not None else None,
                "status": self.status,
                "outcome_code": self.outcome_code,
                "batch_id": self.batch_id,
                "task_id": self.task_id,
                "lifecycle_status": self.lifecycle_status,
                "batch_outcome_code": self.batch_outcome_code,
                "phase": self.phase,
                "attempts_started": self.attempts_started,
                "page_visits": self.page_visits,
                "page_visits_unknown": self.page_visits_unknown,
                "verification_resume_visits": self.verification_resume_visits,
                "retry_visits": self.retry_visits,
                "retry_max": self.operating_metrics_retry_max,
                "retry_total": self.retry_total,
                "retry_completed": self.retry_completed,
                "total": self.total,
                "completed": self.completed,
                "succeeded": self.succeeded,
                "failed": self.failed,
                "remaining": max(self.total - self.completed, 0),
                "verification_required": self.verification_required,
                "operating_metrics_counts": dict(self.operating_metrics_counts),
                "current_competitor_id": self.current_competitor_id,
                "browser_open": self.browser_open,
                "runner_active": self.runner_active,
                "auto_resume_attempt": self.auto_resume_attempt,
                "auto_resume_max": self.auto_resume_max,
                "cooldown_remaining_seconds": self.cooldown_remaining_seconds,
                "resting_remaining_seconds": self.resting_remaining_seconds,
                "items": [
                    {
                        "competitor_id": item.competitor_id,
                        "status": item.status,
                        "error_code": item.error_code,
                        "message": item.message,
                        "outcome": item.outcome,
                        "operating_metrics_status": item.operating_metrics_status,
                    }
                    for item in self.items
                ],
            }


BATCH_RUNTIME = BatchRuntime()


def acquire_collection_slot(
    *,
    batch_reservation: int | None = None,
    runtime: BatchRuntime = BATCH_RUNTIME,
    collection_lock: Any | None = None,
) -> bool:
    """Acquire the collection lock under the batch reservation protocol."""
    lock = COLLECTION_LOCK if collection_lock is None else collection_lock
    if not lock.acquire(blocking=False):
        return False
    owns_batch_reservation = runtime.owns_reservation(batch_reservation)
    if batch_reservation is None and runtime.is_busy():
        lock.release()
        return False
    if batch_reservation is not None and not owns_batch_reservation:
        lock.release()
        return False
    return True


class CompetitorNotFoundError(LookupError):
    pass


class CollectionInProgressError(RuntimeError):
    pass


class CollectionPartialDataError(ValueError):
    pass


class CollectionError(RuntimeError):
    def __init__(self, code: str, message: str, operating_metrics_status: str = "not_attempted") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.operating_metrics_status = operating_metrics_status


@dataclass(frozen=True)
class CollectionResult:
    competitor: Competitor
    snapshot: ProductSnapshot | None
    collection_run: CollectionRun
    sku_count: int
    outcome: str
    operating_metrics_status: str = "not_attempted"
    operating_metrics: list[OperatingMetricObservation] = field(default_factory=list)
    operating_metric_data: list[OperatingMetricData] = field(default_factory=list)


def create_collection_batch(
    db: Session,
    competitor_ids: list[int],
    config: BatchConfig,
    *,
    trigger_kind: str,
    scheduler_occurrence_key: str | None = None,
) -> CollectionBatch:
    now = datetime.now(timezone.utc)
    batch = CollectionBatch(
        task_id=str(uuid4()), trigger_kind=trigger_kind, created_at=now,
        lifecycle_status="created", settings_snapshot=asdict(config),
        planned_products=len(dict.fromkeys(competitor_ids)), scheduler_occurrence_key=scheduler_occurrence_key,
    )
    db.add(batch)
    db.flush()
    db.add_all([
        CollectionBatchItem(batch_id=batch.id, position=position, competitor_id=competitor_id)
        for position, competitor_id in enumerate(dict.fromkeys(competitor_ids))
    ])
    db.commit()
    return batch


def fail_created_batch(session_factory: Callable[[], Session], batch_id: int) -> bool:
    """Close a persisted plan when Runner dispatch fails before it starts."""
    with session_factory() as db:
        batch = db.get(CollectionBatch, batch_id)
        if batch is None or batch.lifecycle_status != "created":
            return False
        for item in db.scalars(select(CollectionBatchItem).where(CollectionBatchItem.batch_id == batch_id)):
            if item.final_result is None:
                item.final_result = "not_executed"
                item.execution_status = "not_executed"
                item.stop_reason = "runner_start_failed"
        batch.lifecycle_status = "terminal"
        batch.finished_at = datetime.now(timezone.utc)
        batch.outcome_code = "infrastructure_error"
        batch.protection_reason = "runner_start_failed"
        batch.protection_details = "采集 Runner 启动失败，计划未执行"
        db.commit()
        return True


def _batch_item_context(session_factory: Callable[[], Session], batch_id: int | None, competitor_id: int) -> tuple[int | None, int | None]:
    if batch_id is None:
        return None, None
    with session_factory() as db:
        item = db.scalar(select(CollectionBatchItem).where(
            CollectionBatchItem.batch_id == batch_id,
            CollectionBatchItem.competitor_id == competitor_id,
        ))
        if item is None:
            return None, None
        latest_attempt = db.scalar(select(CollectionRun.attempt_number).where(
            CollectionRun.collection_batch_item_id == item.id,
        ).order_by(CollectionRun.attempt_number.desc()).limit(1)) or 0
        return item.id, latest_attempt + 1


def _refresh_item_exception_counts(db: Session, item: CollectionBatchItem) -> None:
    counts = dict(db.execute(select(OperatingMetricObservation.status, func.count())
        .join(CollectionRun, CollectionRun.id == OperatingMetricObservation.collection_run_id)
        .where(CollectionRun.collection_batch_item_id == item.id)
        .group_by(OperatingMetricObservation.status)).all())
    for status in ("placeholder", "source_unavailable", "loading", "read_failed"):
        setattr(item, f"{status}_count", counts.get(status, 0))
    item.technical_exception_count = sum(counts.get(status, 0) for status in ("source_unavailable", "loading", "read_failed"))


def _save_item_result(
    session_factory: Callable[[], Session], item_id: int | None, *,
    base_result: str, operating_status: str, final_result: str | None,
    protection_reason: str | None = None,
) -> None:
    if item_id is None:
        return
    with session_factory() as db:
        item = db.get(CollectionBatchItem, item_id)
        if item is None:
            return
        item.base_result = base_result
        item.operating_metrics_status = operating_status
        item.execution_status = "failed" if base_result == "failed" else "completed" if final_result else "running"
        item.final_result = final_result
        item.protection_reason = protection_reason
        _refresh_item_exception_counts(db, item)
        db.commit()


def operating_metrics_status(observations: list[OperatingMetricData]) -> str:
    observed = sum(item.status == "observed" for item in observations)
    if observed == 8:
        return "success"
    if observed:
        return "partial"
    if len(observations) == 8 and all(item.status == "placeholder" for item in observations):
        return "no_values"
    return "failed"


def collection_failure_details(exc: BaseException) -> tuple[str, str]:
    if isinstance(exc, LoginRequiredError):
        return "1688_login_required", "1688 登录状态已失效"
    if isinstance(exc, VerificationRequiredError):
        return "1688_verification_required", "1688 需要完成验证"
    if isinstance(exc, PageUnavailableError):
        return "1688_page_unavailable", "商品页面暂时无法访问"
    if isinstance(exc, CollectionTimeoutError):
        return "collection_timeout", "商品页面加载超时"
    if isinstance(exc, OfferIdMismatchError):
        return "offer_id_mismatch", "采集到的商品与目标竞品不一致"
    if isinstance(exc, CollectionParseError):
        return "collection_parse_failed", "无法解析商品页面"
    if isinstance(exc, CollectionPartialDataError):
        return "collection_partial_data", "采集结果缺少必要商品信息"
    return "collection_failed", "采集失败，请稍后重试"


def collect_product(
    url: str,
    offer_id: str,
    *,
    browser_context: object | None = None,
    on_navigation_claim: Callable[[], None] | None = None,
    on_navigation_confirmed: Callable[[], None] | None = None,
    include_page_result: bool = False,
) -> ProductData | CollectionPageResult:
    """Collect and validate a product before any new monitoring row exists."""
    try:
        kwargs = {}
        if browser_context is not None:
            kwargs["context"] = browser_context
        if on_navigation_claim is not None:
            kwargs["on_navigation_claim"] = on_navigation_claim
            kwargs["on_navigation_confirmed"] = on_navigation_confirmed
        result = collect_1688_product(url, offer_id, **kwargs)
        page_result = result if isinstance(result, CollectionPageResult) else None
        if isinstance(result, CollectionPageResult):
            if result.offer_id != offer_id:
                raise OfferIdMismatchError(
                    f"offer_id mismatch: expected {offer_id}, got {result.offer_id}"
                )
            if result.product is None:
                raise result.product_error or CollectionParseError("product facts unavailable")
            product = result.product
        else:
            product = result
        if isinstance(product, ProductData) and (not isinstance(product.shop_name, str) or not product.shop_name.strip()):
            raise CollectionError(
                "shop_name_unavailable",
                "无法确认店铺名称，未添加监控商品，请重试",
            )
        normalized = _normalize_product(product, offer_id)
        if include_page_result:
            return CollectionPageResult(offer_id, normalized, None, page_result.operating_metrics if page_result else [])
        return normalized
    except OfflineProductDetected as exc:
        raise CollectionError(
            "shop_name_unavailable",
            "无法确认店铺名称，未添加监控商品，请重试",
        ) from exc
    except CollectionError:
        raise
    except Exception as exc:
        code, message = collection_failure_details(exc)
        raise CollectionError(code, message) from exc


def _decimal(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("invalid price") from exc
    if not result.is_finite() or result < 0:
        raise ValueError("invalid price")
    return result


def _normalize_product(product: ProductData, expected_offer_id: str) -> ProductData:
    if not isinstance(product, ProductData):
        raise CollectionPartialDataError("invalid product data")
    if product.offer_id != expected_offer_id:
        raise OfferIdMismatchError(
            f"offer_id mismatch: expected {expected_offer_id}, got {product.offer_id}"
        )
    title = product.title.strip() if isinstance(product.title, str) else ""
    shop_name = product.shop_name.strip() if isinstance(product.shop_name, str) else ""
    if not title or not shop_name:
        raise CollectionPartialDataError("missing required product fields")
    if product.product_status not in {"unknown", "active", "offline"}:
        raise CollectionPartialDataError("invalid product status")
    if product.collection_source not in {"html", "network", "mixed"}:
        raise CollectionPartialDataError("invalid collection source")
    if not isinstance(product.captured_at, datetime):
        raise CollectionPartialDataError("invalid captured_at")
    if (
        isinstance(product.min_order_quantity, bool)
        or (
            product.min_order_quantity is not None
            and (
                not isinstance(product.min_order_quantity, int)
                or product.min_order_quantity < 1
            )
        )
    ):
        raise CollectionPartialDataError("invalid min order quantity")

    try:
        price_min = _decimal(product.price_min)
        price_max = _decimal(product.price_max)
    except ValueError as exc:
        raise CollectionPartialDataError("invalid price") from exc
    if price_min is not None and price_max is not None and price_min > price_max:
        raise CollectionPartialDataError("invalid price range")

    skus: list[SkuData] = []
    if not isinstance(product.skus, list):
        raise CollectionPartialDataError("invalid sku data")
    for sku in product.skus:
        if (
            not isinstance(sku, SkuData)
            or not isinstance(sku.sku_id, str)
            or not isinstance(sku.sku_name, str)
            or not sku.sku_id.strip()
            or not sku.sku_name.strip()
        ):
            raise CollectionPartialDataError("invalid sku data")
        if isinstance(sku.stock, bool) or (sku.stock is not None and not isinstance(sku.stock, int)):
            raise CollectionPartialDataError("invalid stock")
        if sku.stock is not None and sku.stock < 0:
            raise CollectionPartialDataError("invalid stock")
        try:
            sku_price = _decimal(sku.price)
        except ValueError as exc:
            raise CollectionPartialDataError("invalid sku price") from exc
        skus.append(
            SkuData(
                sku_id=sku.sku_id.strip(),
                sku_name=sku.sku_name.strip(),
                stock=sku.stock,
                price=sku_price,
            )
        )

    normalized_main_image_url = normalize_main_image_url(product.main_image_url)
    image_urls: list[str] = []
    if normalized_main_image_url is not None:
        image_urls.append(normalized_main_image_url)
    if isinstance(product.image_urls, list):
        for raw_image_url in product.image_urls:
            image_url = normalize_main_image_url(raw_image_url)
            if image_url is not None and image_url not in image_urls:
                image_urls.append(image_url)

    return ProductData(
        offer_id=expected_offer_id,
        title=title,
        shop_name=shop_name,
        main_image_url=normalized_main_image_url,
        image_urls=image_urls,
        price_min=price_min,
        price_max=price_max,
        product_status=(
            "active" if product.product_status == "unknown" else product.product_status
        ),
        collection_source=product.collection_source,
        captured_at=product.captured_at,
        skus=skus,
        min_order_quantity=product.min_order_quantity,
    )


def _mark_failed(
    db: Session,
    run_id: int,
    error_type: str,
    error_message: str,
    operating_status: str = "not_attempted",
) -> None:
    db.rollback()
    run = db.scalar(select(CollectionRun).where(CollectionRun.id == run_id))
    if run is None:
        return
    run.status = "failed"
    run.operating_metrics_status = operating_status
    run.finished_at = datetime.now(timezone.utc)
    run.error_type = error_type
    run.error_message = error_message
    db.commit()


def _collect_single_batch(db, competitor_id, *, browser_context, runtime, on_external_access, stop_waiting_for_metrics):
    competitor = db.get(Competitor, competitor_id)
    if competitor is None:
        raise CompetitorNotFoundError
    if not competitor.is_active:
        raise CollectionError("competitor_inactive", "该竞品已停止监控，无法立即采集")
    if not acquire_collection_slot(runtime=runtime):
        raise CollectionInProgressError
    token = None
    batch_id = None
    bind = db.get_bind()
    factory = lambda: Session(bind=bind, expire_on_commit=False)
    try:
        if not runtime.reserve([competitor_id], BatchConfig(operating_metrics_retry_max=0)):
            raise CollectionInProgressError
        token = runtime.reservation_token()
        batch = create_collection_batch(db, [competitor_id], BatchConfig(operating_metrics_retry_max=0), trigger_kind="manual_single")
        batch_id = batch.id
        batch.started_at = datetime.now(timezone.utc)
        batch.lifecycle_status = "running"
        db.commit()
        runtime.bind_batch(batch)
        runtime.set_current(competitor_id)
        item = db.scalar(select(CollectionBatchItem).where(CollectionBatchItem.batch_id == batch_id))
        item_id = item.id
    except Exception:
        if token is not None:
            runtime.finish("collect_failed")
        raise
    finally:
        COLLECTION_LOCK.release()
    result = None
    caught = None
    try:
        result = collect_competitor(db, competitor_id, browser_context=browser_context, batch_runtime=runtime,
                                    batch_reservation=token, batch_item_id=item_id, attempt_kind="first_pass", attempt_number=1,
                                    on_external_access=on_external_access, stop_waiting_for_metrics=stop_waiting_for_metrics,
                                    on_attempt_started=runtime.record_attempt_started)
        return result
    except Exception as exc:
        caught = exc
        raise
    finally:
        try:
            with factory() as final_db:
                row = final_db.get(CollectionBatchItem, item_id)
                run = final_db.scalar(select(CollectionRun).where(CollectionRun.collection_batch_item_id == item_id).order_by(CollectionRun.id.desc()))
                if run is not None:
                    _refresh_item_exception_counts(final_db, row)
                    row.base_result = "success" if run.status == "success" else "failed"
                    row.operating_metrics_status = run.operating_metrics_status
                    row.final_result = "verification_required" if run.error_type == "1688_verification_required" else "final_failed" if run.status != "success" or row.technical_exception_count else "first_pass_success"
                    row.execution_status = "failed" if row.base_result == "failed" else "completed"
                    row.stop_reason = run.error_type
                else:
                    row.final_result, row.execution_status = "not_executed", "not_executed"
                final_db.commit()
                if run is not None:
                    runtime.record(BatchItemResult(competitor_id, "verification_required" if run.error_type == "1688_verification_required" else "success" if run.status == "success" else "failed", run.error_type, run.error_message, result.outcome if result else None, run.operating_metrics_status))
            runtime.finish("verification_required" if isinstance(caught, CollectionError) and caught.code == "1688_verification_required" else "partial_failure" if caught else "success")
            _finalize_persisted_batch(factory, batch_id, runtime)
            with factory() as final_db:
                finished = final_db.get(CollectionBatch, batch_id)
                runtime.finish(finished.outcome_code, status="verification_required" if finished.outcome_code == "verification_required" else "completed")
        finally:
            runtime.mark_runner_stopped()


def collect_competitor(
    db: Session,
    competitor_id: int,
    *,
    browser_context: object | None = None,
    batch_reservation: int | None = None,
    batch_runtime: BatchRuntime = BATCH_RUNTIME,
    on_external_access: Callable[[], None] | None = None,
    batch_item_id: int | None = None,
    attempt_kind: str | None = None,
    attempt_number: int | None = None,
    stop_waiting_for_metrics: Callable[[], bool] | None = None,
    on_attempt_started: Callable[[], None] | None = None,
) -> CollectionResult:
    if batch_item_id is None and batch_reservation is None:
        return _collect_single_batch(db, competitor_id, browser_context=browser_context, runtime=batch_runtime,
                                     on_external_access=on_external_access, stop_waiting_for_metrics=stop_waiting_for_metrics)
    competitor = db.get(Competitor, competitor_id)
    if competitor is None:
        raise CompetitorNotFoundError
    if not competitor.is_active:
        raise CollectionError("competitor_inactive", "该竞品已停止监控，无法立即采集")
    if not acquire_collection_slot(batch_reservation=batch_reservation, runtime=batch_runtime):
        raise CollectionInProgressError

    competitor_id_value = competitor.id
    competitor_url = competitor.url
    competitor_offer_id = competitor.offer_id
    run: CollectionRun | None = None
    run_id: int
    try:
        started_at = datetime.now(timezone.utc)
        run = CollectionRun(
            competitor_id=competitor.id,
            collection_batch_item_id=batch_item_id,
            attempt_number=attempt_number,
            attempt_kind=attempt_kind,
            started_at=started_at,
            status="running",
            operating_metrics_status="not_attempted",
        )
        db.add(run)
        try:
            db.flush()
            run_id = run.id
            if batch_item_id is not None:
                item = db.get(CollectionBatchItem, batch_item_id)
                if item is None:
                    raise ValueError("collection batch item disappeared")
                item.execution_status = "running"
                item.attempts_started += 1
            db.commit()
            if batch_item_id is not None and on_attempt_started is not None:
                on_attempt_started()
        except Exception as exc:
            db.rollback()
            raise CollectionError("collection_save_failed", "采集结果保存失败") from exc

        try:
            if batch_item_id is None and on_external_access is not None:
                on_external_access()
            def claim_navigation() -> None:
                current_run = db.get(CollectionRun, run_id)
                if current_run is None or current_run.navigation_claimed_at is not None:
                    raise CollectionError("collection_save_failed", "采集导航状态保存失败")
                current_run.navigation_claimed_at = datetime.now(timezone.utc)
                db.commit()

            def confirm_navigation() -> None:
                current_run = db.get(CollectionRun, run_id)
                if current_run is None or current_run.navigation_claimed_at is None:
                    raise CollectionError("collection_save_failed", "采集导航状态缺失")
                if current_run.navigation_confirmed_at is None:
                    now = datetime.now(timezone.utc)
                    current_run.navigation_confirmed_at = now
                    if batch_item_id is not None:
                        item = db.get(CollectionBatchItem, batch_item_id)
                        if item is None:
                            raise CollectionError("collection_save_failed", "采集批次记录缺失")
                        item.page_visits += 1
                        if attempt_kind == "verification_resume":
                            item.verification_resume_visits += 1
                        elif attempt_kind == "operating_metrics_retry":
                            item.retry_visits += 1
                    db.commit()
                    if on_external_access is not None:
                        on_external_access()
                    if batch_item_id is not None:
                        batch_runtime.record_page_visit(attempt_kind)

            navigation_kwargs = {
                "on_navigation_claim": claim_navigation,
                "on_navigation_confirmed": confirm_navigation,
            } if batch_item_id is not None else {}
            if stop_waiting_for_metrics is not None and "stop_waiting_for_metrics" in inspect.signature(collect_1688_product).parameters:
                navigation_kwargs["stop_waiting_for_metrics"] = stop_waiting_for_metrics
            page_result = (
                collect_1688_product(
                    competitor_url, competitor_offer_id,
                    **navigation_kwargs,
                )
                if browser_context is None
                else collect_1688_product(
                    competitor_url, competitor_offer_id, context=browser_context,
                    **navigation_kwargs,
                )
            )
            if isinstance(page_result, ProductData):
                page_result = CollectionPageResult(
                    page_result.offer_id, page_result, None,
                    [OperatingMetricData(key, "source_unavailable", None,
                        "1688_official_procurement_assistant_top", competitor_offer_id,
                        datetime.now(timezone.utc), "未提供经营指标读取结果")
                     for key in ("listing_time", "monthly_deal", "monthly_dropship", "annual_units", "annual_orders", "review_count", "positive_rate", "pickup_rate")],
                )
            if competitor.platform != "1688" or not isinstance(page_result, CollectionPageResult) or page_result.offer_id != competitor_offer_id:
                raise OfferIdMismatchError("page Offer ID does not match the monitored Offer")
            expected_keys = {"listing_time", "monthly_deal", "monthly_dropship", "annual_units", "annual_orders", "review_count", "positive_rate", "pickup_rate"}
            if (
                len(page_result.operating_metrics) != 8
                or {item.metric_key for item in page_result.operating_metrics} != expected_keys
                or any(item.offer_id != competitor_offer_id for item in page_result.operating_metrics)
                or any(item.status not in {"observed", "placeholder", "loading", "source_unavailable", "read_failed"} for item in page_result.operating_metrics)
            ):
                raise OfferIdMismatchError("page metric identity or source could not be verified")
            product = _normalize_product(page_result.product, competitor_offer_id) if page_result.product is not None else None
            metrics_status = operating_metrics_status(page_result.operating_metrics)
        except OfflineProductDetected:
            try:
                now = datetime.now(timezone.utc)
                if competitor.status == "active":
                    db.add(
                        ChangeEvent(
                            competitor_id=competitor_id_value,
                            snapshot_id=None,
                            collection_run_id=run_id,
                            change_type="product_offline",
                            entity_key=None,
                            old_value="active",
                            new_value="offline",
                            detected_at=now,
                        )
                    )
                competitor.status = "offline"
                competitor.last_collected_at = now
                competitor.updated_at = now
                run.status = "success"
                run.operating_metrics_status = "not_attempted"
                run.finished_at = now
                run.error_type = None
                run.error_message = None
                db.commit()
            except Exception as exc:
                _mark_failed(db, run_id, "collection_save_failed", "采集结果保存失败")
                raise CollectionError("collection_save_failed", "采集结果保存失败") from exc
            return CollectionResult(
                competitor=competitor,
                snapshot=None,
                collection_run=run,
                sku_count=0,
                outcome="offline",
                operating_metrics_status="not_attempted",
            )
        except Exception as exc:
            error_type, error_message = collection_failure_details(exc)
            operating_status = "blocked" if isinstance(exc, (VerificationRequiredError, OfferIdMismatchError)) else "not_attempted"
            _mark_failed(db, run_id, error_type, error_message, operating_status)
            raise CollectionError(error_type, error_message, operating_status) from exc

        metric_rows = [OperatingMetricObservation(
            competitor_id=competitor_id_value,
            collection_run_id=run_id,
            platform="1688",
            offer_id=item.offer_id,
            metric_key=item.metric_key,
            status=item.status,
            raw_value=item.raw_value,
            source=item.source,
            observed_at=item.observed_at,
            reason=item.reason,
        ) for item in page_result.operating_metrics]

        if product is None:
            error_type, error_message = collection_failure_details(
                page_result.product_error or CollectionParseError("product facts unavailable")
            )
            try:
                db.add_all(metric_rows)
                run.status = "failed"
                run.operating_metrics_status = metrics_status
                run.finished_at = datetime.now(timezone.utc)
                run.error_type = error_type
                run.error_message = error_message
                db.commit()
            except Exception as exc:
                _mark_failed(db, run_id, "collection_save_failed", "采集结果保存失败", "failed")
                raise CollectionError("collection_save_failed", "采集结果保存失败", "failed") from exc
            raise CollectionError(error_type, error_message, metrics_status)

        try:
            previous = db.scalar(
                select(ProductSnapshot)
                .options(selectinload(ProductSnapshot.skus))
                .where(ProductSnapshot.competitor_id == competitor_id_value)
                .order_by(ProductSnapshot.captured_at.desc(), ProductSnapshot.id.desc())
                .limit(1)
            )
            previous_status = competitor.status
            drafts = detect_changes(previous, product) if previous_status == "active" else []
            snapshot = ProductSnapshot(
                competitor_id=competitor_id_value,
                captured_at=product.captured_at,
                title=product.title,
                shop_name=product.shop_name,
                main_image_url=product.main_image_url,
                image_urls=product.image_urls,
                price_min=product.price_min,
                price_max=product.price_max,
                min_order_quantity=product.min_order_quantity,
                product_status=product.product_status,
                collection_source=product.collection_source,
                skus=[
                    SkuSnapshot(
                        sku_id=sku.sku_id,
                        sku_name=sku.sku_name,
                        stock=sku.stock,
                        price=sku.price,
                    )
                    for sku in product.skus
                ],
            )
            db.add(snapshot)
            db.add_all(metric_rows)
            db.flush()

            detected_at = datetime.now(timezone.utc)
            db.add_all(
                [
                    ChangeEvent(
                        competitor_id=competitor_id_value,
                        snapshot_id=snapshot.id,
                        collection_run_id=run_id,
                        change_type=draft.change_type,
                        entity_key=draft.entity_key,
                        old_value=draft.old_value,
                        new_value=draft.new_value,
                        delta_value=draft.delta_value,
                        delta_rate=draft.delta_rate,
                        detected_at=detected_at,
                    )
                    for draft in drafts
                ]
            )
            if previous_status == "offline":
                db.add(
                    ChangeEvent(
                        competitor_id=competitor_id_value,
                        snapshot_id=snapshot.id,
                        collection_run_id=run_id,
                        change_type="product_online",
                        entity_key=None,
                        old_value="offline",
                        new_value="active",
                        detected_at=detected_at,
                    )
                )

            now = datetime.now(timezone.utc)
            competitor.title = product.title
            competitor.shop_name = product.shop_name
            competitor.main_image_url = product.main_image_url
            competitor.status = product.product_status
            competitor.last_collected_at = product.captured_at
            competitor.updated_at = now
            apply_collected_ownership(db, competitor, product.shop_name)

            run.status = "success"
            run.operating_metrics_status = metrics_status
            run.finished_at = now
            run.error_type = None
            run.error_message = None
            db.commit()
        except Exception as exc:
            _mark_failed(db, run_id, "collection_save_failed", "采集结果保存失败", "failed")
            raise CollectionError("collection_save_failed", "采集结果保存失败", "failed") from exc

        return CollectionResult(
            competitor=competitor,
            snapshot=snapshot,
            collection_run=run,
            sku_count=len(product.skus),
            outcome="active",
            operating_metrics_status=metrics_status,
            operating_metrics=metric_rows,
            operating_metric_data=page_result.operating_metrics,
        )
    finally:
        COLLECTION_LOCK.release()


def _batch_error_item(competitor_id: int, code: str, message: str) -> BatchItemResult:
    return BatchItemResult(
        competitor_id=competitor_id,
        status="failed",
        error_code=code,
        message=message,
    )


def _batch_validation_items(
    session_factory: Callable[[], Session],
    competitor_ids: list[int],
) -> tuple[list[int], list[BatchItemResult]]:
    with session_factory() as db:
        competitors = {
            competitor.id: competitor
            for competitor in db.scalars(
                select(Competitor).where(Competitor.id.in_(competitor_ids))
            ).all()
        }
    runnable: list[int] = []
    rejected: list[BatchItemResult] = []
    for competitor_id in competitor_ids:
        competitor = competitors.get(competitor_id)
        if competitor is None:
            rejected.append(_batch_error_item(competitor_id, "competitor_not_found", "竞品不存在"))
        elif not competitor.is_active:
            rejected.append(
                _batch_error_item(
                    competitor_id,
                    "competitor_inactive",
                    "该竞品已停止监控，无法采集",
                )
            )
        else:
            runnable.append(competitor_id)
    return runnable, rejected


def _finalize_persisted_batch(session_factory: Callable[[], Session], batch_id: int, runtime: BatchRuntime) -> None:
    with session_factory() as db:
        batch = db.get(CollectionBatch, batch_id)
        if batch is None or batch.lifecycle_status == "terminal":
            return
        items = db.scalars(select(CollectionBatchItem).where(CollectionBatchItem.batch_id == batch_id)).all()
        for item in items:
            if item.final_result is None:
                item.final_result = "not_executed" if item.attempts_started == 0 else "final_failed"
                item.execution_status = "not_executed" if item.attempts_started == 0 else "completed"
        successes = sum(item.final_result in {"first_pass_success", "verification_resume_success", "retry_success"} for item in items)
        base_failures = sum(item.base_result == "failed" for item in items)
        technical_failures = sum(item.final_result == "final_failed" and (item.technical_exception_count or item.operating_metrics_status == "failed") for item in items)
        unexecuted = sum(item.final_result == "not_executed" for item in items)
        runtime_state = runtime.snapshot()
        if runtime.outcome_code == "collect_failed":
            outcome = "infrastructure_error"
        elif runtime.outcome_code == "verification_required" or runtime_state["status"] == "verification_required" or any(
            item.status == "verification_required" for item in runtime.items
        ) or any(item.protection_reason == "1688_verification_required" for item in items):
            outcome = "verification_required"
        elif runtime.end_requested():
            outcome = "user_ended"
        elif unexecuted:
            outcome = "infrastructure_error"
            batch.protection_reason = batch.protection_reason or "unattributed_unexecuted_items"
        elif base_failures == 0 and technical_failures == 0:
            outcome = "success"
        elif base_failures == 0:
            outcome = "partial_success"
        elif successes:
            outcome = "partial_failure"
        else:
            outcome = "collect_failed"
        batch.lifecycle_status = "terminal"
        batch.finished_at = datetime.now(timezone.utc)
        batch.outcome_code = outcome
        db.commit()
        runtime.set_persisted_batch_state("terminal", outcome)


def recover_interrupted_batches(session_factory: Callable[[], Session]) -> int:
    """Close stale persisted batches once at startup; never relaunch their plan."""
    recovered = 0
    with session_factory() as db:
        batches = db.scalars(select(CollectionBatch).where(CollectionBatch.lifecycle_status.in_(("created", "running")))).all()
        for batch in batches:
            if batch.trigger_kind == "add_links":
                from app.collection.add_links import finalize_add_batch
                finalize_add_batch(db, batch, "interrupted")
                recovered += 1
                continue
            items = db.scalars(select(CollectionBatchItem).where(CollectionBatchItem.batch_id == batch.id)).all()
            items_by_id = {item.id: item for item in items}
            runs = db.scalars(select(CollectionRun).where(
                CollectionRun.collection_batch_item_id.in_(items_by_id),
            ).order_by(CollectionRun.attempt_number, CollectionRun.id)).all() if items_by_id else []
            runs_by_item: dict[int, list[CollectionRun]] = {}
            for run in runs:
                item = items_by_id[run.collection_batch_item_id]
                runs_by_item.setdefault(item.id, []).append(run)
                if run.status == "running":
                    if run.navigation_claimed_at is not None and run.navigation_confirmed_at is None:
                        item.page_visits_unknown += 1
                        if run.attempt_kind == "verification_resume":
                            item.verification_resume_visits += 1
                        elif run.attempt_kind == "operating_metrics_retry":
                            item.retry_visits += 1
                        run.navigation_terminal_reason = "interrupted_navigation_unknown"
                    elif run.navigation_confirmed_at is not None:
                        run.navigation_terminal_reason = "interrupted_after_navigation"
                    else:
                        run.navigation_terminal_reason = "interrupted_before_navigation"
                    run.status = "failed"
                    run.finished_at = datetime.now(timezone.utc)
                    run.error_type = "batch_interrupted"
                    run.error_message = "Backend 重启时批次尚未完成"
            for item in items:
                _refresh_item_exception_counts(db, item)
                history = runs_by_item.get(item.id, [])
                latest = next((run for run in reversed(history) if run.navigation_terminal_reason != "interrupted_before_navigation"), None)
                if latest is None and history:
                    latest = history[-1]
                if item.final_result is None and latest is not None:
                    if latest.navigation_terminal_reason == "interrupted_before_navigation":
                        item.final_result = "not_executed"
                        item.execution_status = "not_executed"
                        item.stop_reason = "batch_interrupted"
                    elif latest.status == "success":
                        tech = db.scalar(select(func.count()).select_from(OperatingMetricObservation).where(
                            OperatingMetricObservation.collection_run_id == latest.id,
                            OperatingMetricObservation.status.in_(("loading", "source_unavailable", "read_failed")),
                        )) or 0
                        item.base_result = "success"
                        item.operating_metrics_status = latest.operating_metrics_status
                        item.final_result = "final_failed" if tech else "retry_success" if latest.attempt_kind == "operating_metrics_retry" else "verification_resume_success" if latest.attempt_kind == "verification_resume" else "first_pass_success"
                    elif latest.error_type == "1688_verification_required":
                        item.final_result = "verification_required"
                        item.operating_metrics_status = "blocked"
                    else:
                        item.base_result = "failed"
                        item.final_result = "final_failed"
                        item.stop_reason = latest.error_type or "batch_interrupted"
                    item.execution_status = (
                        "not_executed" if item.final_result == "not_executed"
                        else "completed" if item.final_result != "final_failed" else "failed"
                    )
                if item.final_result is None:
                    item.final_result = "not_executed" if item.attempts_started == 0 else "final_failed"
                    item.execution_status = "not_executed" if item.attempts_started == 0 else "completed"
                    item.stop_reason = "batch_interrupted"
            batch.lifecycle_status = "terminal"
            batch.outcome_code = "interrupted"
            batch.finished_at = datetime.now(timezone.utc)
            batch.protection_reason = "backend_restart"
            batch.protection_details = "重启后已收口，旧批次不会自动续跑"
            recovered += 1
        if recovered:
            db.commit()
    return recovered


def run_batch_collection(
    session_factory: Callable[[], Session],
    competitor_ids: list[int],
    runtime: BatchRuntime = BATCH_RUNTIME,
    *,
    config: BatchConfig | None = None,
    cooldown_seconds: float | None = None,
    batch_reservation: int | None = None,
    persisted_batch_id: int | None = None,
) -> None:
    """Run one serial batch in one worker thread and one headed Context."""
    if runtime.work_kind == "add_links":
        from app.collection.add_links import execute_add_batch
        execute_add_batch(session_factory, persisted_batch_id, runtime, batch_reservation, config)
        return
    config = config or BatchConfig()
    if cooldown_seconds is not None:
        config = BatchConfig(
            item_interval_seconds=config.item_interval_seconds,
            continuous_collection_count=config.continuous_collection_count,
            batch_rest_seconds=config.batch_rest_seconds,
            verification_cooldown_seconds=cooldown_seconds,
            auto_resume_max=config.auto_resume_max,
            operating_metrics_retry_max=config.operating_metrics_retry_max,
        )
    lock_acquired = False
    context = None
    verification_page = None
    try:
        batch_reservation = batch_reservation or runtime.reservation_token()
        if not acquire_collection_slot(batch_reservation=batch_reservation, runtime=runtime):
            runtime.finish("collection_in_progress")
            return
        lock_acquired = True

        if persisted_batch_id is not None:
            with session_factory() as db:
                batch = db.get(CollectionBatch, persisted_batch_id)
                if batch is None or batch.lifecycle_status != "created":
                    runtime.finish("collect_failed")
                    return
                batch.lifecycle_status = "running"
                batch.started_at = datetime.now(timezone.utc)
                db.commit()
                runtime.set_persisted_batch_state("running")

        runnable_ids, validation_items = _batch_validation_items(session_factory, competitor_ids)
        for item in validation_items:
            runtime.record(item)
            if persisted_batch_id is not None:
                with session_factory() as db:
                    item_row = db.scalar(select(CollectionBatchItem).where(
                        CollectionBatchItem.batch_id == persisted_batch_id,
                        CollectionBatchItem.competitor_id == item.competitor_id,
                    ))
                    if item_row is not None:
                        item_row.base_result = "failed"
                        item_row.final_result = "final_failed"
                        item_row.execution_status = "failed"
                        item_row.stop_reason = item.error_code
                        db.commit()
        if not runnable_ids:
            runtime.finish("partial_failure" if validation_items else "success")
            return

        with sync_playwright() as playwright:
            context = _launch_context(playwright)
            runtime.set_browser_open(True)
            move_context_offscreen(context)

            def pause_if_requested() -> bool:
                nonlocal context
                if not runtime.pause_requested():
                    return False
                if runtime.snapshot()["remaining"] == 0:
                    return False
                _close_quietly(context)
                context = None
                runtime.set_browser_open(False)
                if runtime.stop_requested():
                    return True
                runtime.mark_paused()
                if not runtime.wait_for_resume():
                    return True
                context = _launch_context(playwright)
                runtime.set_browser_open(True)
                move_context_offscreen(context)
                return False

            stop_batch = False
            continuous_accesses = 0
            retry_candidates: list[tuple[int, int, bool, bool, str]] = []
            circuit_streak = 0
            circuit_breaker_open = False
            for position, competitor_id in enumerate(runnable_ids):
                if pause_if_requested():
                    stop_batch = True
                    break
                current_attempt_kind = "first_pass"
                while True:
                    if runtime.stop_requested():
                        stop_batch = True
                        break
                    runtime.set_current(competitor_id)
                    retry_current = False
                    item_id: int | None = None
                    external_accesses_before = runtime.external_accesses()
                    try:
                        item_id, attempt_number = _batch_item_context(session_factory, persisted_batch_id, competitor_id)
                        with session_factory() as db:
                            attempt_kwargs = {}
                            if persisted_batch_id is not None:
                                attempt_kwargs = {
                                    "batch_item_id": item_id,
                                    "attempt_kind": current_attempt_kind,
                                    "attempt_number": attempt_number,
                                    "stop_waiting_for_metrics": lambda: runtime.pause_requested() or runtime.stop_requested(),
                                    "on_attempt_started": runtime.record_attempt_started,
                                }
                            collection_result = collect_competitor(
                                db,
                                competitor_id,
                                browser_context=context,
                                batch_reservation=batch_reservation,
                                batch_runtime=runtime,
                                on_external_access=runtime.record_external_access,
                                **attempt_kwargs,
                            )
                    except CollectionError as exc:
                        if exc.code == "1688_verification_required":
                            if runtime.snapshot()["auto_resume_attempt"] >= config.auto_resume_max:
                                runtime.record(
                                    BatchItemResult(
                                        competitor_id=competitor_id,
                                        status="verification_required",
                                        error_code=exc.code,
                                        message=exc.message,
                                        operating_metrics_status="blocked",
                                    )
                                )
                                _save_item_result(session_factory, item_id, base_result="not_attempted", operating_status="blocked", final_result="verification_required", protection_reason="verification_required")
                                runtime.mark_verification()
                                verification_page = (
                                    getattr(context, "pages", []) or [None]
                                )[0]
                                restore_context_window(context, verification_page)
                                while not runtime.stop_requested():
                                    try:
                                        if not getattr(context, "pages", []):
                                            break
                                    except Exception:
                                        break
                                    runtime.wait_for_stop(0.25)
                                stop_batch = True
                                break

                            runtime.begin_auto_resume()
                            continuous_accesses = 0
                            _close_quietly(context)
                            context = None
                            runtime.set_browser_open(False)
                            runtime.enter_cooldown(config.verification_cooldown_seconds)
                            if not runtime.wait_for_cooldown(config.verification_cooldown_seconds):
                                stop_batch = True
                                break
                            runtime.set_running()
                            if runtime.pause_requested():
                                if pause_if_requested():
                                    stop_batch = True
                                    break
                            else:
                                context = _launch_context(playwright)
                                runtime.set_browser_open(True)
                                move_context_offscreen(context)
                            retry_current = True
                            current_attempt_kind = "verification_resume"
                            runtime.set_phase("verification_resume")
                            continue
                        if exc.code == "collection_save_failed":
                            runtime.finish("collect_failed")
                            stop_batch = True
                            break
                        runtime.record(BatchItemResult(
                            competitor_id, "failed", exc.code, exc.message,
                            operating_metrics_status=exc.operating_metrics_status,
                        ))
                        _save_item_result(session_factory, item_id, base_result="failed", operating_status=exc.operating_metrics_status, final_result="final_failed", protection_reason=exc.code)
                    except CompetitorNotFoundError:
                        runtime.record(
                            _batch_error_item(competitor_id, "competitor_not_found", "竞品不存在")
                        )
                        _save_item_result(session_factory, item_id, base_result="failed", operating_status="not_attempted", final_result="final_failed", protection_reason="competitor_not_found")
                    except Exception as exc:
                        runtime.finish("collect_failed")
                        stop_batch = True
                        break
                    else:
                        metrics = list(getattr(collection_result, "operating_metric_data", []))
                        technical = [metric for metric in metrics if metric.status in {"loading", "source_unavailable", "read_failed"}]
                        all_unavailable = len(metrics) == 8 and all(metric.status == "source_unavailable" for metric in metrics)
                        if current_attempt_kind == "first_pass":
                            if all_unavailable:
                                circuit_streak += 1
                            elif any(metric.status in {"observed", "placeholder"} for metric in metrics):
                                circuit_streak = 0
                            if circuit_streak >= 3:
                                circuit_breaker_open = True
                                if persisted_batch_id is not None:
                                    with session_factory() as db:
                                        batch = db.get(CollectionBatch, persisted_batch_id)
                                        if batch is not None:
                                            batch.protection_reason = "source_unavailable_circuit_breaker"
                                            batch.protection_details = "连续 3 个不同商品首轮八项经营字段均来源不可用"
                                            batch.circuit_breaker_streak = circuit_streak
                                            db.commit()
                            elif persisted_batch_id is not None:
                                with session_factory() as db:
                                    batch = db.get(CollectionBatch, persisted_batch_id)
                                    if batch is not None:
                                        batch.circuit_breaker_streak = circuit_streak
                                        db.commit()
                        eligible = any(
                            metric.status == "loading" or (
                                metric.status == "source_unavailable"
                                and "标题不存在或不唯一" in (metric.reason or "")
                            ) for metric in metrics
                        )
                        retry_pending = persisted_batch_id is not None and config.operating_metrics_retry_max > 0 and eligible
                        if item_id is not None:
                            if retry_pending:
                                retry_candidates.append((competitor_id, item_id, bool(technical), current_attempt_kind == "verification_resume", collection_result.operating_metrics_status))
                                _save_item_result(session_factory, item_id, base_result="success", operating_status=collection_result.operating_metrics_status, final_result=None)
                            else:
                                final = "final_failed" if technical else "verification_resume_success" if current_attempt_kind == "verification_resume" else "first_pass_success"
                                _save_item_result(session_factory, item_id, base_result="success", operating_status=collection_result.operating_metrics_status, final_result=final)
                        if not retry_pending:
                            runtime.record(BatchItemResult(
                                competitor_id, "success", outcome=getattr(collection_result, "outcome", None),
                                operating_metrics_status=getattr(collection_result, "operating_metrics_status", "not_attempted"),
                            ))
                    finally:
                        if not retry_current:
                            runtime.set_current(None)
                    break
                if stop_batch:
                    break
                if runtime.stop_requested():
                    stop_batch = True
                    break
                if pause_if_requested():
                    stop_batch = True
                    break
                if runtime.external_accesses() <= external_accesses_before:
                    continue
                continuous_accesses += 1
                if position == len(runnable_ids) - 1:
                    continue
                if config.batch_rest_seconds > 0 and continuous_accesses >= config.continuous_collection_count:
                    runtime.enter_resting(config.batch_rest_seconds)
                    if not runtime.wait_for_resting(config.batch_rest_seconds):
                        stop_batch = True
                        break
                    runtime.set_running()
                    continuous_accesses = 0
                elif runtime.wait_for_stop(config.item_interval_seconds):
                    stop_batch = True
                    break

            if persisted_batch_id is not None and retry_candidates:
                runtime.set_phase("operating_metrics_retry")
                runtime.set_retry_total(len(retry_candidates))
                if circuit_breaker_open:
                    with session_factory() as db:
                        batch = db.get(CollectionBatch, persisted_batch_id)
                        if batch is not None:
                            batch.circuit_breaker_cancelled += len(retry_candidates)
                        for competitor_id, item_id, _had_technical, was_verification_resume, first_status in retry_candidates:
                            item = db.get(CollectionBatchItem, item_id)
                            if item is not None:
                                item.final_result = "final_failed"
                                item.execution_status = "completed"
                                item.cancelled_retry_count += 1
                                item.protection_reason = "cancelled_circuit_breaker"
                                item.stop_reason = "source_unavailable_circuit_breaker"
                            runtime.record(BatchItemResult(competitor_id, "success", operating_metrics_status=first_status))
                            runtime.record_retry_completed()
                        db.commit()
                else:
                    for retry_position, (competitor_id, item_id, had_technical, was_verification_resume, first_status) in enumerate(retry_candidates):
                        current_status = first_status
                        current_base_result = "success"
                        current_error_code = current_error_message = None
                        retry_stopped = False
                        retry_verification = False
                        for retry_index in range(min(config.operating_metrics_retry_max, 2)):
                            if runtime.stop_requested() or pause_if_requested():
                                retry_stopped = True
                                stop_batch = True
                                break
                            if config.continuous_collection_count > 0 and continuous_accesses >= config.continuous_collection_count:
                                runtime.enter_resting(config.batch_rest_seconds)
                                if not runtime.wait_for_resting(config.batch_rest_seconds):
                                    retry_stopped = True
                                    stop_batch = True
                                    break
                                runtime.set_running()
                                continuous_accesses = 0
                            elif runtime.external_accesses() > 0 and runtime.wait_for_stop(config.item_interval_seconds):
                                retry_stopped = True
                                stop_batch = True
                                break
                            active_item_id, attempt_number = _batch_item_context(session_factory, persisted_batch_id, competitor_id)
                            runtime.set_current(competitor_id)
                            external_before = runtime.external_accesses()
                            try:
                                with session_factory() as db:
                                    result = collect_competitor(
                                        db, competitor_id, browser_context=context,
                                        batch_reservation=batch_reservation, batch_runtime=runtime,
                                        on_external_access=runtime.record_external_access,
                                        batch_item_id=active_item_id, attempt_kind="operating_metrics_retry",
                                        attempt_number=attempt_number,
                                        stop_waiting_for_metrics=lambda: runtime.pause_requested() or runtime.stop_requested(),
                                        on_attempt_started=runtime.record_attempt_started,
                                    )
                            except CollectionError as exc:
                                if exc.code == "1688_verification_required":
                                    if runtime.snapshot()["auto_resume_attempt"] >= config.auto_resume_max:
                                        _save_item_result(session_factory, item_id, base_result="success", operating_status=exc.operating_metrics_status, final_result="final_failed", protection_reason=exc.code)
                                        runtime.mark_verification()
                                        verification_page = (getattr(context, "pages", []) or [None])[0]
                                        restore_context_window(context, verification_page)
                                        while not runtime.stop_requested():
                                            try:
                                                if not getattr(context, "pages", []):
                                                    break
                                            except Exception:
                                                break
                                            runtime.wait_for_stop(0.25)
                                        retry_stopped = True
                                        retry_verification = True
                                        stop_batch = True
                                        break
                                    runtime.begin_auto_resume()
                                    runtime.set_phase("verification_resume")
                                    continuous_accesses = 0
                                    _close_quietly(context)
                                    context = None
                                    runtime.set_browser_open(False)
                                    runtime.enter_cooldown(config.verification_cooldown_seconds)
                                    if not runtime.wait_for_cooldown(config.verification_cooldown_seconds):
                                        retry_stopped = True
                                        stop_batch = True
                                        break
                                    runtime.set_running()
                                    if pause_if_requested():
                                        retry_stopped = True
                                        stop_batch = True
                                        break
                                    if context is None:
                                        context = _launch_context(playwright)
                                        runtime.set_browser_open(True)
                                        move_context_offscreen(context)
                                    active_item_id, resume_number = _batch_item_context(session_factory, persisted_batch_id, competitor_id)
                                    while True:
                                        try:
                                            with session_factory() as db:
                                                resumed = collect_competitor(
                                                    db, competitor_id, browser_context=context,
                                                    batch_reservation=batch_reservation, batch_runtime=runtime,
                                                    on_external_access=runtime.record_external_access,
                                                    batch_item_id=active_item_id, attempt_kind="verification_resume",
                                                    attempt_number=resume_number,
                                                    stop_waiting_for_metrics=lambda: runtime.pause_requested() or runtime.stop_requested(),
                                                    on_attempt_started=runtime.record_attempt_started,
                                                )
                                        except CollectionError as resume_error:
                                            if resume_error.code == "1688_verification_required":
                                                if runtime.snapshot()["auto_resume_attempt"] < config.auto_resume_max:
                                                    runtime.begin_auto_resume()
                                                    runtime.set_phase("verification_resume")
                                                    _close_quietly(context)
                                                    context = None
                                                    runtime.set_browser_open(False)
                                                    runtime.enter_cooldown(config.verification_cooldown_seconds)
                                                    if not runtime.wait_for_cooldown(config.verification_cooldown_seconds):
                                                        retry_stopped = stop_batch = True
                                                        break
                                                    runtime.set_running()
                                                    if pause_if_requested():
                                                        retry_stopped = stop_batch = True
                                                        break
                                                    if context is None:
                                                        context = _launch_context(playwright)
                                                        runtime.set_browser_open(True)
                                                        move_context_offscreen(context)
                                                    active_item_id, resume_number = _batch_item_context(session_factory, persisted_batch_id, competitor_id)
                                                    continue
                                                _save_item_result(session_factory, item_id, base_result="success", operating_status="blocked", final_result="final_failed", protection_reason=resume_error.code)
                                                runtime.mark_verification()
                                                verification_page = (getattr(context, "pages", []) or [None])[0]
                                                restore_context_window(context, verification_page)
                                                while not runtime.stop_requested():
                                                    try:
                                                        if not getattr(context, "pages", []):
                                                            break
                                                    except Exception:
                                                        break
                                                    runtime.wait_for_stop(0.25)
                                                retry_stopped = retry_verification = stop_batch = True
                                                break
                                            if resume_error.code == "collection_save_failed":
                                                runtime.finish("collect_failed")
                                                retry_stopped = stop_batch = True
                                                break
                                            current_base_result = "failed"
                                            current_status = resume_error.operating_metrics_status
                                            current_error_code, current_error_message = resume_error.code, resume_error.message
                                            _save_item_result(session_factory, item_id, base_result=current_base_result, operating_status=current_status, final_result="final_failed", protection_reason=resume_error.code)
                                            retry_stopped = True
                                            break
                                        else:
                                            break
                                    if retry_verification or stop_batch:
                                        break
                                    if retry_stopped:
                                        break
                                    current_status = resumed.operating_metrics_status
                                    runtime.set_phase("operating_metrics_retry")
                                    resume_metrics = list(getattr(resumed, "operating_metric_data", []))
                                    still_technical = not resume_metrics or any(metric.status in {"loading", "source_unavailable", "read_failed"} for metric in resume_metrics)
                                    resume_still_eligible = any(metric.status == "loading" or (
                                        metric.status == "source_unavailable" and "标题不存在或不唯一" in (metric.reason or "")
                                    ) for metric in resume_metrics)
                                    if resume_still_eligible and retry_index + 1 < min(config.operating_metrics_retry_max, 2):
                                        _save_item_result(session_factory, item_id, base_result="success", operating_status=current_status, final_result=None)
                                        retry_stopped = False
                                        continue
                                    _save_item_result(
                                        session_factory, item_id, base_result="success", operating_status=current_status,
                                        final_result="final_failed" if still_technical else "verification_resume_success",
                                    )
                                    retry_stopped = False
                                    break
                                if exc.code == "collection_save_failed":
                                    runtime.finish("collect_failed")
                                    retry_stopped = stop_batch = True
                                    break
                                current_base_result = "failed"
                                current_status = exc.operating_metrics_status
                                current_error_code, current_error_message = exc.code, exc.message
                                _save_item_result(session_factory, item_id, base_result=current_base_result, operating_status=current_status, final_result="final_failed", protection_reason=exc.code)
                                break
                            except Exception:
                                current_base_result = "failed"
                                current_status = "failed"
                                current_error_code, current_error_message = "collection_failed", "采集失败"
                                _save_item_result(session_factory, item_id, base_result=current_base_result, operating_status=current_status, final_result="final_failed", protection_reason=current_error_code)
                                break
                            if runtime.external_accesses() > external_before:
                                continuous_accesses += 1
                            current_status = result.operating_metrics_status
                            metric_data = list(getattr(result, "operating_metric_data", []))
                            remaining_technical = not metric_data or any(metric.status in {"loading", "source_unavailable", "read_failed"} for metric in metric_data)
                            recovered = had_technical and not remaining_technical and any(metric.status in {"observed", "placeholder"} for metric in metric_data)
                            if not remaining_technical:
                                _save_item_result(session_factory, item_id, base_result="success", operating_status=current_status, final_result="retry_success" if recovered else "verification_resume_success" if was_verification_resume else "first_pass_success")
                                break
                            still_eligible = any(metric.status == "loading" or (
                                metric.status == "source_unavailable" and "标题不存在或不唯一" in (metric.reason or "")
                            ) for metric in metric_data)
                            if retry_index + 1 >= min(config.operating_metrics_retry_max, 2) or not still_eligible:
                                _save_item_result(session_factory, item_id, base_result="success", operating_status=current_status, final_result="final_failed")
                                break
                        runtime.set_current(None)
                        if retry_stopped and not retry_verification:
                            _save_item_result(session_factory, item_id, base_result=current_base_result, operating_status=current_status, final_result="final_failed", protection_reason=current_error_code or "batch_stopped")
                        runtime.record(BatchItemResult(competitor_id, current_base_result, error_code=current_error_code, message=current_error_message, operating_metrics_status=current_status))
                        runtime.record_retry_completed()
                        if stop_batch:
                            break
            if persisted_batch_id is not None:
                with session_factory() as db:
                    pending_items = db.scalars(select(CollectionBatchItem).where(
                        CollectionBatchItem.batch_id == persisted_batch_id,
                        CollectionBatchItem.final_result.is_(None),
                    )).all()
                    for item in pending_items:
                        item.final_result = "not_executed" if item.attempts_started == 0 else "final_failed"
                        item.execution_status = "not_executed" if item.attempts_started == 0 else "completed"
                        item.stop_reason = "batch_stopped" if runtime.stop_requested() else item.stop_reason
                    db.commit()

    except Exception:
        runtime.finish("collect_failed")
    finally:
        _close_quietly(context)
        runtime.mark_runner_stopped()
        snapshot = runtime.snapshot()
        if runtime.end_requested() and snapshot["status"] == "stopping":
            runtime.finish("user_ended", status="stopped")
        elif runtime.stop_requested() and snapshot["status"] in {"running", "pausing", "paused", "resting", "cooling_down"}:
            runtime.finish("collect_failed")
        elif snapshot["status"] in {"running", "pausing", "paused", "resting", "cooling_down"} and snapshot["remaining"] == 0:
            runtime.finish(
                "partial_failure" if runtime.has_failures() else "partial_success" if any(
                    item.operating_metrics_status != "success" for item in runtime.items
                ) else "success"
            )
        elif runtime.is_running():
            runtime.finish(
                "partial_failure" if runtime.has_failures() else "partial_success" if any(
                    item.operating_metrics_status != "success" for item in runtime.items
                ) else "success"
            )
        try:
            if persisted_batch_id is not None:
                _finalize_persisted_batch(session_factory, persisted_batch_id, runtime)
        finally:
            runtime.set_phase(None)
            if lock_acquired:
                COLLECTION_LOCK.release()


def start_batch_task(
    session_factory: Callable[[], Session],
    competitor_ids: list[int],
    runtime: BatchRuntime = BATCH_RUNTIME,
    batch_reservation: int | None = None,
    config: BatchConfig | None = None,
    persisted_batch_id: int | None = None,
) -> asyncio.Task[Any]:
    task = asyncio.create_task(
        asyncio.to_thread(
            run_batch_collection,
            session_factory,
            competitor_ids,
            runtime,
            batch_reservation=batch_reservation,
            config=config,
            persisted_batch_id=persisted_batch_id,
        )
    )
    runtime.attach_task(task)
    return task


async def shutdown_batch_runner(runtime: BatchRuntime = BATCH_RUNTIME) -> None:
    if not runtime.is_busy():
        return
    runtime.request_stop()
    task = runtime.get_task()
    if task is not None:
        await task
