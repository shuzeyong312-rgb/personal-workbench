from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from threading import Event

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collection.service import (
    COLLECTION_LOCK,
    CollectionError,
    CollectionInProgressError,
    collect_competitor,
)
from app.models import CollectionRun, Competitor


logger = logging.getLogger(__name__)
_DAY = timedelta(hours=24)


@dataclass
class DailyCollectionResult:
    due: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    interrupted: int = 0


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_due(started_at: datetime | None, now: datetime) -> bool:
    return started_at is None or _as_utc(now) - _as_utc(started_at) >= _DAY


def run_daily_collection_cycle(
    session_factory: Callable[[], Session],
    *,
    now: datetime | None = None,
    collect: Callable[[Session, int], object] = collect_competitor,
    stop_event: Event | None = None,
) -> DailyCollectionResult:
    checked_at = _as_utc(now or datetime.now(timezone.utc))
    result = DailyCollectionResult()
    logger.info("daily collection cycle start")

    with session_factory() as session:
        competitors = session.execute(
            select(Competitor.id, Competitor.is_active).order_by(Competitor.id)
        ).all()

    for competitor_id, initially_active in competitors:
        if stop_event is not None and stop_event.is_set():
            result.interrupted += 1
            logger.info("daily collection cycle stopped")
            break
        if not initially_active:
            result.skipped += 1
            continue
        if not COLLECTION_LOCK.acquire(blocking=False):
            result.interrupted += 1
            logger.info("daily collection competitor=%s busy", competitor_id)
            break
        try:
            if stop_event is not None and stop_event.is_set():
                result.interrupted += 1
                logger.info("daily collection cycle stopped")
                break
            with session_factory() as session:
                competitor = session.get(Competitor, competitor_id)
                if competitor is None or not competitor.is_active:
                    result.skipped += 1
                    continue
                latest_run = session.scalar(
                    select(CollectionRun)
                    .where(CollectionRun.competitor_id == competitor_id)
                    .order_by(CollectionRun.started_at.desc(), CollectionRun.id.desc())
                    .limit(1)
                )
                if latest_run is not None and not _is_due(latest_run.started_at, checked_at):
                    result.skipped += 1
                    continue
                if stop_event is not None and stop_event.is_set():
                    result.interrupted += 1
                    logger.info("daily collection cycle stopped")
                    break

                result.due += 1
                try:
                    collect(session, competitor_id)
                except CollectionInProgressError:
                    result.interrupted += 1
                    logger.info("daily collection competitor=%s busy", competitor_id)
                    break
                except CollectionError as exc:
                    result.failed += 1
                    logger.warning(
                        "daily collection competitor=%s failure code=%s message=%s",
                        competitor_id,
                        exc.code,
                        exc.message,
                    )
                else:
                    result.success += 1
                    logger.info("daily collection competitor=%s success", competitor_id)
        finally:
            COLLECTION_LOCK.release()

    logger.info(
        "daily collection cycle end due=%s success=%s failed=%s skipped=%s interrupted=%s",
        result.due,
        result.success,
        result.failed,
        result.skipped,
        result.interrupted,
    )
    return result
