from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from hashlib import sha256
import json
from threading import Event

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.collection.service import BATCH_RUNTIME, COLLECTION_LOCK, BatchConfig, acquire_collection_slot, create_collection_batch
from app.models import CollectionBatch, CollectionRun, Competitor
from app.settings import batch_config_values, get_competitor_monitoring_settings

_DAY = timedelta(hours=24)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@dataclass
class FixedDailyState:
    signature: tuple[object, ...] | None = None
    enabled: bool | None = None
    lifecycle_started_at: datetime | None = None


@dataclass(frozen=True)
class AutoBatchStart:
    competitor_ids: list[int]
    config: BatchConfig
    reservation_token: int
    batch_id: int


def _boundary(now: datetime, value: str, local_tz: object) -> datetime:
    hour, minute = map(int, value.split(":"))
    return datetime.combine(now.astimezone(local_tz).date(), time(hour, minute), tzinfo=local_tz).astimezone(timezone.utc)


def _scheduled_times(settings: dict[str, object]) -> list[str]:
    if settings["auto_collection_strategy"] == "fixed_daily":
        return list(settings["auto_collection_times"])
    start = str(settings["auto_collection_time"])
    hour, minute = map(int, start.split(":"))
    start_minutes = hour * 60 + minute
    interval_minutes = int(settings["auto_collection_interval_hours"]) * 60
    return [
        f"{point // 60:02d}:{point % 60:02d}"
        for point in (start_minutes + index * interval_minutes for index in range(int(settings["auto_collection_daily_limit"])))
    ]


def _latest_occurrence(now: datetime, settings: dict[str, object], local_tz: object) -> datetime | None:
    points = [_boundary(now, value, local_tz) for value in _scheduled_times(settings)]
    return max((point for point in points if point <= now), default=None)


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


def _sync_scheduler_state(
    settings: dict[str, object], state: FixedDailyState, checked_at: datetime,
    lifecycle_started_at: datetime | None,
) -> tuple[bool, str]:
    """Apply enable/config changes as a fresh in-process scheduler lifecycle."""
    was_enabled, previous_signature = state.enabled, state.signature
    if not settings["auto_collection_enabled"]:
        state.enabled = False
        return False, str(settings["auto_collection_strategy"])
    state.enabled = True
    strategy = str(settings["auto_collection_strategy"])
    signature = (
        strategy, settings["auto_collection_time"], tuple(settings["auto_collection_times"]),
        settings["auto_collection_interval_hours"], settings["auto_collection_daily_limit"],
        settings["auto_collection_missed_policy"],
    )
    if was_enabled is False or (previous_signature is not None and signature != previous_signature):
        state.lifecycle_started_at = checked_at
    elif state.lifecycle_started_at is None:
        state.lifecycle_started_at = _as_utc(lifecycle_started_at or checked_at)
    state.signature = signature
    return True, strategy


def _eligible_occurrence(settings: dict[str, object], state: FixedDailyState, checked_at: datetime, local_tz: object) -> datetime | None:
    if settings["auto_collection_strategy"] == "rolling_24h":
        return None
    occurrence = _latest_occurrence(checked_at, settings, local_tz)
    if occurrence is not None and settings["auto_collection_missed_policy"] == "skip" and state.lifecycle_started_at is not None and state.lifecycle_started_at >= occurrence:
        return None
    return occurrence


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
    enabled, strategy = _sync_scheduler_state(settings, state, checked_at, lifecycle_started_at)
    if not enabled:
        return None
    boundary = _eligible_occurrence(settings, state, checked_at, tz)
    if strategy != "rolling_24h" and boundary is None:
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
            final_enabled, final_strategy = _sync_scheduler_state(settings, state, checked_at, lifecycle_started_at)
            if not final_enabled:
                return None
            final_boundary = _eligible_occurrence(settings, state, checked_at, tz)
            if final_strategy != "rolling_24h" and final_boundary is None:
                return None
            ids = _due_ids(db, now=checked_at, strategy=final_strategy, boundary=final_boundary)
            if not ids:
                return None
            if db.scalar(select(CollectionBatch.id).where(CollectionBatch.lifecycle_status.in_(("created", "running"))).limit(1)) is not None:
                return None
            config = BatchConfig(**batch_config_values(settings))
            due_facts = []
            for competitor_id in sorted(ids):
                latest = db.scalar(select(CollectionRun).where(
                    CollectionRun.competitor_id == competitor_id,
                ).order_by(CollectionRun.started_at.desc(), CollectionRun.id.desc()).limit(1))
                due_facts.append((competitor_id, latest.id if latest else None, _as_utc(latest.started_at).isoformat() if latest else None))
            if final_boundary is not None:
                occurrence_key = f"{final_strategy}:{final_boundary.isoformat()}"
                existing = db.scalar(select(CollectionBatch.id).where(
                    CollectionBatch.scheduler_occurrence_key.startswith(occurrence_key),
                ).limit(1))
                if existing is not None:
                    return None
            else:
                existing_keys = db.scalars(select(CollectionBatch.scheduler_occurrence_key).where(
                    CollectionBatch.scheduler_occurrence_key.is_not(None),
                )).all()
                window = "rolling_24h"
                facts_signature = sha256(json.dumps(due_facts, separators=(",", ":")).encode()).hexdigest()[:16]
                prefix = f"{final_strategy}:{window}:{facts_signature}"
                generation = sum(key.startswith(f"{prefix}:") for key in existing_keys) + 1
                occurrence_key = f"{prefix}:{generation}"
            if not BATCH_RUNTIME.reserve(ids, config):
                return None
            token = BATCH_RUNTIME.reservation_token()
            assert token is not None
            # Binding a committed plan must not perform another fallible database read.
            db.expire_on_commit = False
            try:
                batch = create_collection_batch(
                    db, ids, config, trigger_kind="scheduled",
                    scheduler_occurrence_key=occurrence_key,
                )
            except IntegrityError:
                db.rollback()
                BATCH_RUNTIME.finish("collect_failed")
                winner = db.scalar(select(CollectionBatch).where(CollectionBatch.scheduler_occurrence_key == occurrence_key))
                if winner is None:
                    raise
                BATCH_RUNTIME.finish("success")
                return None
            except Exception:
                db.rollback()
                BATCH_RUNTIME.finish("collect_failed")
                raise
            BATCH_RUNTIME.bind_batch(batch)
            return AutoBatchStart(ids, config, token, batch.id)
    finally:
        COLLECTION_LOCK.release()
