import asyncio
import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from threading import Event

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from datetime import datetime, timezone

from app.collection.daily import FixedDailyState, prepare_auto_batch
from app.collection.service import BATCH_RUNTIME, fail_created_batch, recover_interrupted_batches, shutdown_batch_runner, start_batch_task
from app.collection_runs import router as collection_runs_router
from app.collection_batches import router as collection_batches_router
from app.competitors import router as competitors_router
from app.competitor_detail import router as competitor_detail_router
from app.competitor_groups import router as competitor_groups_router
from app.group_detail import router as group_detail_router
from app.group_attention import router as group_attention_router
from app.database import engine
from app.dashboard import router as dashboard_router
from app.settings import router as settings_router
from app.product_library import router as product_library_router


DAILY_COLLECTION_INTERVAL_SECONDS = 60
logger = logging.getLogger(__name__)


def _session_factory() -> Session:
    return Session(engine)


async def _wait_for_stop(stop_event: asyncio.Event, timeout: float) -> bool:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout)
    except asyncio.TimeoutError:
        return False
    return True


async def _daily_collection_loop(
    stop_event: asyncio.Event, thread_stop_event: Event
) -> None:
    state = FixedDailyState()
    lifecycle_started_at = datetime.now(timezone.utc)
    pending_batch_id = None
    while not thread_stop_event.is_set():
        try:
            if pending_batch_id is None:
                start = await asyncio.to_thread(
                    prepare_auto_batch, _session_factory, state=state,
                    lifecycle_started_at=lifecycle_started_at, stop_event=thread_stop_event,
                )
                if start is not None:
                    pending_batch_id = start.batch_id
                    if not thread_stop_event.is_set():
                        try:
                            start_batch_task(_session_factory, start.competitor_ids, batch_reservation=start.reservation_token, config=start.config, persisted_batch_id=start.batch_id)
                        except Exception:
                            logger.error("Automatic collection runner dispatch failed")
                        else:
                            pending_batch_id = None
            if pending_batch_id is not None:
                # Retain failed dispatch cleanup across locked ticks before making a new plan.
                fail_created_batch(_session_factory, pending_batch_id)
                pending_batch_id = None
                BATCH_RUNTIME.finish("collect_failed")
                BATCH_RUNTIME.set_persisted_batch_state("terminal", "infrastructure_error")
        except OperationalError as exc:
            if not isinstance(exc.orig, sqlite3.OperationalError) or getattr(exc.orig, "sqlite_errorcode", 0) & 0xff not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                if pending_batch_id is not None:
                    BATCH_RUNTIME.finish("collect_failed")
                raise
            logger.warning("Automatic collection database locked; retrying next tick")
        if thread_stop_event.is_set() or await _wait_for_stop(stop_event, DAILY_COLLECTION_INTERVAL_SECONDS):
            if pending_batch_id is not None:
                # Startup recovery closes the durable plan if shutdown cannot write it.
                BATCH_RUNTIME.finish("collect_failed")
            return


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    session_factory = getattr(_app.state, "collection_session_factory", None) or _session_factory
    recover_interrupted_batches(session_factory)
    if os.getenv("PERSONAL_WORKBENCH_DISABLE_SCHEDULER") == "1":
        yield
        return
    stop_event = asyncio.Event()
    thread_stop_event = Event()
    scheduler_task = asyncio.create_task(_daily_collection_loop(stop_event, thread_stop_event))
    try:
        yield
    finally:
        thread_stop_event.set()
        stop_event.set()
        try:
            await scheduler_task
        finally:
            await shutdown_batch_runner()


app = FastAPI(lifespan=lifespan)
app.include_router(competitors_router)
app.include_router(collection_runs_router)
app.include_router(collection_batches_router)
app.include_router(competitor_detail_router)
app.include_router(competitor_groups_router)
app.include_router(group_detail_router)
app.include_router(group_attention_router)
app.include_router(dashboard_router)
app.include_router(settings_router)
app.include_router(product_library_router)


@app.exception_handler(RequestValidationError)
async def product_library_validation_error(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/api/product-library/"):
        code = "invalid_decisions" if request.url.path.endswith("/confirm") else "invalid_product"
        return JSONResponse(status_code=422, content={"code": code, "message": "请求字段或格式无效"})
    return await request_validation_exception_handler(request, exc)


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict):
        return JSONResponse(status_code=exc.status_code, content=exc.detail, headers=exc.headers)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
