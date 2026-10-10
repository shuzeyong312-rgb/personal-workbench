import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from math import ceil
from threading import Event, Lock, RLock
from time import monotonic
from typing import Any, Callable

from sqlalchemy import select
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
from app.collection.types import ProductData, SkuData
from app.changes import detect_changes
from app.models import ChangeEvent, CollectionRun, Competitor, ProductSnapshot, SkuSnapshot
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


@dataclass(frozen=True)
class BatchItemResult:
    competitor_id: int
    status: str
    error_code: str | None = None
    message: str | None = None
    outcome: str | None = None


class BatchRuntime:
    """The one in-process batch state exposed by the polling endpoint."""

    def __init__(self) -> None:
        self._lock = Lock()
        self.status = "idle"
        self.outcome_code: str | None = None
        self.total = 0
        self.completed = 0
        self.succeeded = 0
        self.failed = 0
        self.verification_required = 0
        self.current_competitor_id: int | None = None
        self.browser_open = False
        self.runner_active = False
        self.auto_resume_attempt = 0
        self.auto_resume_max = BatchConfig().auto_resume_max
        self.cooldown_remaining_seconds = 0
        self.resting_remaining_seconds = 0
        self.external_access_count = 0
        self.items: list[BatchItemResult] = []
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

    def reserve(self, competitor_ids: list[int], config: BatchConfig | None = None) -> bool:
        with self._lock:
            if self.runner_active or self.browser_open:
                return False
            self._reservation_sequence += 1
            self._active_reservation = self._reservation_sequence
            self.status = "running"
            self.outcome_code = None
            self.total = len(competitor_ids)
            self.completed = 0
            self.succeeded = 0
            self.failed = 0
            self.verification_required = 0
            self.current_competitor_id = None
            self.browser_open = False
            self.runner_active = True
            self.auto_resume_attempt = 0
            self.auto_resume_max = (config or BatchConfig()).auto_resume_max
            self.cooldown_remaining_seconds = 0
            self.resting_remaining_seconds = 0
            self.external_access_count = 0
            self.items = []
            self.stop_event = Event()
            self.resume_event = Event()
            self.resume_event.set()
            self._paused_status = None
            self._end_requested = False
            self.task = None
            return True

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

    def wait_for_resting(self, seconds: float) -> bool:
        return self._wait_with_remaining(seconds, "resting_remaining_seconds")

    def _wait_with_remaining(self, seconds: float, field: str) -> bool:
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

    def finish(self, outcome_code: str, *, status: str = "completed") -> None:
        with self._lock:
            self.status = status
            self.outcome_code = outcome_code
            self.current_competitor_id = None
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
            was_collecting = self.status == "running" and self.current_competitor_id is not None
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
                "status": self.status,
                "outcome_code": self.outcome_code,
                "total": self.total,
                "completed": self.completed,
                "succeeded": self.succeeded,
                "failed": self.failed,
                "remaining": max(self.total - self.completed, 0),
                "verification_required": self.verification_required,
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
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class CollectionResult:
    competitor: Competitor
    snapshot: ProductSnapshot | None
    collection_run: CollectionRun
    sku_count: int
    outcome: str


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
) -> ProductData:
    """Collect and validate a product before any new monitoring row exists."""
    try:
        if browser_context is None:
            product = collect_1688_product(url, offer_id)
        else:
            product = collect_1688_product(url, offer_id, context=browser_context)
        if isinstance(product, ProductData) and (not isinstance(product.shop_name, str) or not product.shop_name.strip()):
            raise CollectionError(
                "shop_name_unavailable",
                "无法确认店铺名称，未添加监控商品，请重试",
            )
        return _normalize_product(product, offer_id)
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
) -> None:
    db.rollback()
    run = db.scalar(select(CollectionRun).where(CollectionRun.id == run_id))
    if run is None:
        return
    run.status = "failed"
    run.finished_at = datetime.now(timezone.utc)
    run.error_type = error_type
    run.error_message = error_message
    db.commit()


def collect_competitor(
    db: Session,
    competitor_id: int,
    *,
    browser_context: object | None = None,
    batch_reservation: int | None = None,
    batch_runtime: BatchRuntime = BATCH_RUNTIME,
    on_external_access: Callable[[], None] | None = None,
) -> CollectionResult:
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
            started_at=started_at,
            status="running",
        )
        db.add(run)
        try:
            db.flush()
            run_id = run.id
            db.commit()
        except Exception as exc:
            db.rollback()
            raise CollectionError("collection_save_failed", "采集结果保存失败") from exc

        try:
            if on_external_access is not None:
                on_external_access()
            if browser_context is None:
                product = collect_1688_product(competitor_url, competitor_offer_id)
            else:
                product = collect_1688_product(
                    competitor_url,
                    competitor_offer_id,
                    context=browser_context,
                )
            product = _normalize_product(product, competitor_offer_id)
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
            )
        except Exception as exc:
            error_type, error_message = collection_failure_details(exc)
            _mark_failed(db, run_id, error_type, error_message)
            raise CollectionError(error_type, error_message) from exc

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
            run.finished_at = now
            run.error_type = None
            run.error_message = None
            db.commit()
        except Exception as exc:
            _mark_failed(db, run_id, "collection_save_failed", "采集结果保存失败")
            raise CollectionError("collection_save_failed", "采集结果保存失败") from exc

        return CollectionResult(
            competitor=competitor,
            snapshot=snapshot,
            collection_run=run,
            sku_count=len(product.skus),
            outcome="active",
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


def run_batch_collection(
    session_factory: Callable[[], Session],
    competitor_ids: list[int],
    runtime: BatchRuntime = BATCH_RUNTIME,
    *,
    config: BatchConfig | None = None,
    cooldown_seconds: float | None = None,
    batch_reservation: int | None = None,
) -> None:
    """Run one serial batch in one worker thread and one headed Context."""
    config = config or BatchConfig()
    if cooldown_seconds is not None:
        config = BatchConfig(
            item_interval_seconds=config.item_interval_seconds,
            continuous_collection_count=config.continuous_collection_count,
            batch_rest_seconds=config.batch_rest_seconds,
            verification_cooldown_seconds=cooldown_seconds,
            auto_resume_max=config.auto_resume_max,
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

        runnable_ids, validation_items = _batch_validation_items(session_factory, competitor_ids)
        for item in validation_items:
            runtime.record(item)
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
            for position, competitor_id in enumerate(runnable_ids):
                if pause_if_requested():
                    stop_batch = True
                    break
                while True:
                    if runtime.stop_requested():
                        stop_batch = True
                        break
                    runtime.set_current(competitor_id)
                    retry_current = False
                    external_accesses_before = runtime.external_accesses()
                    try:
                        with session_factory() as db:
                            collection_result = collect_competitor(
                                db,
                                competitor_id,
                                browser_context=context,
                                batch_reservation=batch_reservation,
                                batch_runtime=runtime,
                                on_external_access=runtime.record_external_access,
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
                                    )
                                )
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
                            continue
                        runtime.record(
                            _batch_error_item(competitor_id, exc.code, exc.message)
                        )
                    except CompetitorNotFoundError:
                        runtime.record(
                            _batch_error_item(competitor_id, "competitor_not_found", "竞品不存在")
                        )
                    except Exception:
                        runtime.finish("collect_failed")
                        stop_batch = True
                        break
                    else:
                        runtime.record(
                            BatchItemResult(
                                competitor_id,
                                "success",
                                outcome=getattr(collection_result, "outcome", None),
                            )
                        )
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
                "partial_failure" if runtime.has_failures() else "success"
            )
        elif runtime.is_running():
            runtime.finish(
                "partial_failure" if runtime.has_failures() else "success"
            )
        if lock_acquired:
            COLLECTION_LOCK.release()


def start_batch_task(
    session_factory: Callable[[], Session],
    competitor_ids: list[int],
    runtime: BatchRuntime = BATCH_RUNTIME,
    batch_reservation: int | None = None,
    config: BatchConfig | None = None,
) -> asyncio.Task[Any]:
    task = asyncio.create_task(
        asyncio.to_thread(
            run_batch_collection,
            session_factory,
            competitor_ids,
            runtime,
            batch_reservation=batch_reservation,
            config=config,
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
