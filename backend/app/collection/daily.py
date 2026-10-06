from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from threading import Event

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collection.service import BATCH_RUNTIME, COLLECTION_LOCK, BatchConfig, acquire_collection_slot
from app.models import CollectionRun, Competitor
from app.settings import batch_config_values, get_competitor_monitoring_settings

_DAY = timedelta(hours=24)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@dataclass
class FixedDailyState:
    signature: tuple[object, ...] | None = None
    enabled: bool | None = None


@dataclass(frozen=True)
class AutoBatchStart:
    competitor_ids: list[int]
    config: BatchConfig
    reservation_token: int


def _boundary(now: datetime, value: str, local_tz: object) -> datetime:
    hour, minute = map(int, value.split(":"))
    return datetime.combine(now.astimezone(local_tz).date(), time(hour, minute), tzinfo=local_tz).astimezone(timezone.utc)


def _due_ids(db: Session, *, now: datetime, strategy: str, boundary: datetime | None) -> list[int]:
    due: list[int] = []
    ids = db.scalars(select(Competitor.id).where(Competitor.is_active.is_(True)).order_by(Competitor.id)).all()
    for competitor_id in ids:
        latest = db.scalar(select(CollectionRun).where(CollectionRun.competitor_id == competitor_id).order_by(CollectionRun.started_at.desc(), CollectionRun.id.desc()).limit(1))
        if strategy == "rolling_24h":
            if latest is None or now - _as_utc(latest.started_at) >= _DAY:
                due.append(competitor_id)
        elif boundary is not None and (latest is None or _as_utc(latest.started_at) < boundary):
            due.append(competitor_id)
    return due


def _sync_scheduler_state(settings: dict[str, object], state: FixedDailyState) -> tuple[bool, bool | None, tuple[object, ...] | None, str, tuple[object, ...]]:
    """Apply the one in-process lifecycle transition for either settings read."""
    was_enabled, previous_signature = state.enabled, state.signature
    if not settings["auto_collection_enabled"]:
        state.enabled = False
        return False, was_enabled, previous_signature, "", ()
    state.enabled = True
    strategy = str(settings["auto_collection_strategy"])
    signature = (strategy, settings["auto_collection_time"], settings["auto_collection_missed_policy"])
    if signature != previous_signature:
        state.signature = signature
    return True, was_enabled, previous_signature, strategy, signature


def prepare_auto_batch(
    session_factory: Callable[[], Session], *, now: datetime | None = None,
    local_tz: object | None = None, state: FixedDailyState | None = None,
    lifecycle_started_at: datetime | None = None, stop_event: Event | None = None,
) -> AutoBatchStart | None:
    """Reserve the sole BatchRuntime only after final due IDs are recalculated."""
    if stop_event is not None and stop_event.is_set():
        return None
    checked_at = _as_utc(now or datetime.now(timezone.utc))
    tz = local_tz or datetime.now().astimezone().tzinfo or timezone.utc
    state = state or FixedDailyState()
    with session_factory() as db:
        settings = get_competitor_monitoring_settings(db)
    enabled, was_enabled, previous_signature, strategy, signature = _sync_scheduler_state(settings, state)
    if not enabled:
        return None
    changed = signature != previous_signature
    boundary = _boundary(checked_at, str(settings["auto_collection_time"]), tz) if strategy == "fixed_daily" else None
    if strategy == "fixed_daily":
        if checked_at < boundary:
            return None
        # A post-plan enable/config change behaves like a new scheduler lifecycle;
        # it must not inherit a pending window from the earlier configuration.
        started = checked_at if was_enabled is False or (previous_signature is not None and changed) else _as_utc(lifecycle_started_at or checked_at)
        if started >= boundary and settings["auto_collection_missed_policy"] == "skip":
            return None
    with session_factory() as db:
        if not _due_ids(db, now=checked_at, strategy=strategy, boundary=boundary):
            return None
    if (stop_event is not None and stop_event.is_set()) or not acquire_collection_slot(collection_lock=COLLECTION_LOCK):
        return None
    try:
        if stop_event is not None and stop_event.is_set():
            return None
        with session_factory() as db:
            settings = get_competitor_monitoring_settings(db)
            final_enabled, final_was_enabled, _final_previous, final_strategy, final_signature = _sync_scheduler_state(settings, state)
            if not final_enabled:
                return None
            final_boundary = _boundary(checked_at, str(settings["auto_collection_time"]), tz) if final_strategy == "fixed_daily" else None
            if final_strategy == "fixed_daily":
                if checked_at < final_boundary:
                    return None
                final_started = checked_at if final_was_enabled is False or final_signature != signature else _as_utc(lifecycle_started_at or checked_at)
                if final_started >= final_boundary and settings["auto_collection_missed_policy"] == "skip":
                    return None
            ids = _due_ids(db, now=checked_at, strategy=final_strategy, boundary=final_boundary)
            if not ids:
                return None
            config = BatchConfig(**batch_config_values(settings))
            if not BATCH_RUNTIME.reserve(ids, config):
                return None
            token = BATCH_RUNTIME.reservation_token()
            assert token is not None
            return AutoBatchStart(ids, config, token)
    finally:
        COLLECTION_LOCK.release()
