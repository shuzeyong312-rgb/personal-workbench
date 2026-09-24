import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from threading import Event

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.collection.daily import run_daily_collection_cycle
from app.collection.service import shutdown_batch_runner
from app.competitors import router as competitors_router
from app.competitor_detail import router as competitor_detail_router
from app.competitor_groups import router as competitor_groups_router
from app.group_detail import router as group_detail_router
from app.group_attention import router as group_attention_router
from app.database import engine
from app.dashboard import router as dashboard_router


DAILY_COLLECTION_INITIAL_DELAY_SECONDS = 30
DAILY_COLLECTION_INTERVAL_SECONDS = 60 * 60


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
    if await _wait_for_stop(stop_event, DAILY_COLLECTION_INITIAL_DELAY_SECONDS):
        return
    while not thread_stop_event.is_set():
        await asyncio.to_thread(
            run_daily_collection_cycle,
            _session_factory,
            stop_event=thread_stop_event,
        )
        if thread_stop_event.is_set():
            return
        if await _wait_for_stop(stop_event, DAILY_COLLECTION_INTERVAL_SECONDS):
            return


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    stop_event = asyncio.Event()
    thread_stop_event = Event()
    scheduler_task = asyncio.create_task(_daily_collection_loop(stop_event, thread_stop_event))
    try:
        yield
    finally:
        thread_stop_event.set()
        stop_event.set()
        await scheduler_task
        await shutdown_batch_runner()


app = FastAPI(lifespan=lifespan)
app.include_router(competitors_router)
app.include_router(competitor_detail_router)
app.include_router(competitor_groups_router)
app.include_router(group_detail_router)
app.include_router(group_attention_router)
app.include_router(dashboard_router)


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
