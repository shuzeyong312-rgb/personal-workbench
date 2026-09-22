import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from threading import Event, Lock, RLock
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.collection.collector_1688 import (
    CollectionTimeoutError,
    LoginRequiredError,
    PageUnavailableError,
    VerificationRequiredError,
    collect_1688_product,
    move_context_offscreen,
    restore_context_window,
    sync_playwright,
    _close_quietly,
    _launch_context,
)
from app.collection.parser_1688 import CollectionParseError, OfferIdMismatchError
from app.collection.types import ProductData, SkuData
from app.changes import detect_changes
from app.models import ChangeEvent, CollectionRun, Competitor, ProductSnapshot, SkuSnapshot


COLLECTION_LOCK = RLock()


@dataclass(frozen=True)
class BatchItemResult:
    competitor_id: int
    status: str
    error_code: str | None = None
    message: str | None = None


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
        self.items: list[BatchItemResult] = []
        self.stop_event = Event()
        self.task: asyncio.Task[Any] | None = None

    def is_busy(self) -> bool:
        with self._lock:
            return self.runner_active or self.browser_open

    def reserve(self, competitor_ids: list[int]) -> bool:
        with self._lock:
            if self.runner_active or self.browser_open:
                return False
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
            self.items = []
            self.stop_event = Event()
            self.task = None
            return True

    def attach_task(self, task: asyncio.Task[Any]) -> None:
        with self._lock:
            self.task = task

    def get_task(self) -> asyncio.Task[Any] | None:
        with self._lock:
            return self.task

    def set_browser_open(self, value: bool) -> None:
        with self._lock:
            self.browser_open = value

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

    def mark_verification(self) -> None:
        with self._lock:
            self.status = "verification_required"
            self.outcome_code = "verification_required"

    def is_running(self) -> bool:
        with self._lock:
            return self.status == "running"

    def has_failures(self) -> bool:
        with self._lock:
            return self.failed > 0

    def mark_runner_stopped(self) -> None:
        with self._lock:
            self.runner_active = False
            self.browser_open = False

    def request_stop(self) -> None:
        with self._lock:
            self.stop_event.set()

    def stop_requested(self) -> bool:
        with self._lock:
            return self.stop_event.is_set()

    def wait_for_stop(self, timeout: float) -> bool:
        with self._lock:
            stop_event = self.stop_event
        return stop_event.wait(timeout)

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
                "items": [
                    {
                        "competitor_id": item.competitor_id,
                        "status": item.status,
                        "error_code": item.error_code,
                        "message": item.message,
                    }
                    for item in self.items
                ],
            }


BATCH_RUNTIME = BatchRuntime()


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
    snapshot: ProductSnapshot
    collection_run: CollectionRun
    sku_count: int


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

    return ProductData(
        offer_id=expected_offer_id,
        title=title,
        shop_name=shop_name,
        main_image_url=(
            product.main_image_url.strip()
            if isinstance(product.main_image_url, str) and product.main_image_url.strip()
            else None
        ),
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
) -> CollectionResult:
    competitor = db.get(Competitor, competitor_id)
    if competitor is None:
        raise CompetitorNotFoundError
    if not competitor.is_active:
        raise CollectionError("competitor_inactive", "该竞品已停止监控，无法立即采集")
    if not COLLECTION_LOCK.acquire(blocking=False):
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
            if browser_context is None:
                product = collect_1688_product(competitor_url, competitor_offer_id)
            else:
                product = collect_1688_product(
                    competitor_url,
                    competitor_offer_id,
                    context=browser_context,
                )
            product = _normalize_product(product, competitor_offer_id)
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
            drafts = detect_changes(previous, product)
            snapshot = ProductSnapshot(
                competitor_id=competitor_id_value,
                captured_at=product.captured_at,
                title=product.title,
                shop_name=product.shop_name,
                main_image_url=product.main_image_url,
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
                        change_type=draft.change_type,
                        entity_key=draft.entity_key,
                        old_value=draft.old_value,
                        new_value=draft.new_value,
                        detected_at=detected_at,
                    )
                    for draft in drafts
                ]
            )

            now = datetime.now(timezone.utc)
            competitor.title = product.title
            competitor.shop_name = product.shop_name
            competitor.main_image_url = product.main_image_url
            competitor.status = product.product_status
            competitor.last_collected_at = product.captured_at
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
            snapshot=snapshot,
            collection_run=run,
            sku_count=len(product.skus),
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
) -> None:
    """Run one serial batch in one worker thread and one headed Context."""
    lock_acquired = False
    context = None
    verification_page = None
    try:
        if not COLLECTION_LOCK.acquire(blocking=False):
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

            for competitor_id in runnable_ids:
                if runtime.stop_requested():
                    break
                runtime.set_current(competitor_id)
                try:
                    with session_factory() as db:
                        collect_competitor(
                            db,
                            competitor_id,
                            browser_context=context,
                        )
                except CollectionError as exc:
                    if exc.code == "1688_verification_required":
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
                        break
                    runtime.record(
                        _batch_error_item(competitor_id, exc.code, exc.message)
                    )
                except CompetitorNotFoundError:
                    runtime.record(
                        _batch_error_item(competitor_id, "competitor_not_found", "竞品不存在")
                    )
                except Exception:
                    runtime.finish("collect_failed")
                    break
                else:
                    runtime.record(BatchItemResult(competitor_id, "success"))
                finally:
                    runtime.set_current(None)

    except Exception:
        runtime.finish("collect_failed")
    finally:
        _close_quietly(context)
        runtime.mark_runner_stopped()
        if runtime.is_running():
            runtime.finish(
                "partial_failure" if runtime.has_failures() else "success"
            )
        if lock_acquired:
            COLLECTION_LOCK.release()


def start_batch_task(
    session_factory: Callable[[], Session],
    competitor_ids: list[int],
    runtime: BatchRuntime = BATCH_RUNTIME,
) -> asyncio.Task[Any]:
    task = asyncio.create_task(
        asyncio.to_thread(run_batch_collection, session_factory, competitor_ids, runtime)
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
