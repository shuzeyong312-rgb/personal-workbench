from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.collection import daily
from app.collection.daily import FixedDailyState, prepare_auto_batch
from app.collection.service import BATCH_RUNTIME, collect_competitor
from app.collection.types import ProductData
from app.models import Base, CollectionBatch, CollectionRun, Competitor, SystemSetting

LOCAL = timezone(timedelta(hours=8))
PRE = datetime(2026, 10, 6, 1, 29, tzinfo=timezone.utc)   # 09:29 local
POST = datetime(2026, 10, 6, 1, 31, tzinfo=timezone.utc)  # 09:31 local


@pytest.fixture()
def factory() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    BATCH_RUNTIME.finish("success")
    yield sessionmaker(bind=engine, expire_on_commit=False)
    BATCH_RUNTIME.finish("success")
    engine.dispose()


def competitor(factory: sessionmaker[Session], *, active: bool = True, ownership: str = "competitor") -> int:
    with factory() as db:
        item = Competitor(platform="1688", offer_id=str(100 + db.query(Competitor).count()), url="https://detail.1688.com/offer/1.html", status="unknown", is_active=active, ownership=ownership, created_at=PRE, updated_at=PRE)
        db.add(item); db.commit(); return item.id


def run(factory: sessionmaker[Session], item: int, at: datetime, status: str = "failed") -> None:
    with factory() as db:
        db.add(CollectionRun(competitor_id=item, started_at=at, finished_at=at, status=status)); db.commit()


def settings(factory: sessionmaker[Session], **changes: object) -> None:
    values = {"auto_collection_enabled": True, "auto_collection_strategy": "fixed_daily", "auto_collection_time": "09:30", "auto_collection_times": ["09:30"], "auto_collection_interval_hours": 4, "auto_collection_daily_limit": 3, "auto_collection_missed_policy": "catch_up"}
    keys = {"auto_collection_enabled": "competitor_monitoring_auto_collection_enabled", "auto_collection_strategy": "competitor_monitoring_auto_collection_strategy", "auto_collection_time": "competitor_monitoring_auto_collection_time", "auto_collection_times": "competitor_monitoring_auto_collection_times", "auto_collection_interval_hours": "competitor_monitoring_auto_collection_interval_hours", "auto_collection_daily_limit": "competitor_monitoring_auto_collection_daily_limit", "auto_collection_missed_policy": "competitor_monitoring_auto_collection_missed_policy"}
    with factory() as db:
        for field, key in keys.items():
            existing = db.get(SystemSetting, key)
            if existing is not None:
                values[field] = existing.value == "true" if field == "auto_collection_enabled" else json.loads(existing.value) if field == "auto_collection_times" else int(existing.value) if field in {"auto_collection_interval_hours", "auto_collection_daily_limit"} else existing.value
        values.update(changes)
        for field, value in values.items():
            db.merge(SystemSetting(key=keys[field], value="true" if value is True else "false" if value is False else json.dumps(value) if field == "auto_collection_times" else str(value)))
        db.commit()


def attempt(factory: sessionmaker[Session], state: FixedDailyState, now: datetime, *, started: datetime = PRE):
    result = prepare_auto_batch(factory, now=now, local_tz=LOCAL, state=state, lifecycle_started_at=started)
    if result is not None:
        BATCH_RUNTIME.finish("success")
    return result


def finish_batch(factory: sessionmaker[Session], start) -> None:
    with factory() as db:
        batch = db.get(CollectionBatch, start.batch_id)
        batch.lifecycle_status = "terminal"
        batch.outcome_code = "success"
        db.commit()
    BATCH_RUNTIME.finish("success")


def test_fixed_daily_catch_up_matrix_and_utc_boundary(factory: sessionmaker[Session]) -> None:
    self_id, competitor_id = competitor(factory, ownership="self"), competitor(factory)
    inactive = competitor(factory, active=False)
    settings(factory)
    state = FixedDailyState()
    assert attempt(factory, state, PRE) is None
    start = attempt(factory, state, POST, started=POST)
    assert start and start.competitor_ids == [self_id, competitor_id]
    run(factory, self_id, datetime(2026, 10, 6, 1, 30))
    run(factory, competitor_id, datetime(2026, 10, 6, 1, 31), "success")
    assert attempt(factory, state, POST, started=POST) is None
    run(factory, inactive, datetime(2026, 10, 6, 1, 31))


def test_multiple_daily_points_are_independent_and_same_point_is_not_retriggered(factory: sessionmaker[Session]) -> None:
    first, second = competitor(factory), competitor(factory)
    settings(factory, auto_collection_times=["13:30", "09:30"])
    state = FixedDailyState()
    start = attempt(factory, state, POST, started=PRE)
    assert start and start.competitor_ids == [first, second]
    with factory() as db:
        key = db.get(CollectionBatch, start.batch_id).scheduler_occurrence_key
    finish_batch(factory, start)
    assert attempt(factory, state, POST, started=PRE) is None
    run(factory, first, POST)
    next_point = POST + timedelta(hours=4)
    next_batch = attempt(factory, state, next_point, started=PRE)
    assert next_batch and next_batch.competitor_ids == [first, second]
    with factory() as db:
        next_key = db.get(CollectionBatch, next_batch.batch_id).scheduler_occurrence_key
    assert key != next_key and "T05:30" in next_key


def test_fixed_interval_uses_start_interval_count_and_advances_by_occurrence(factory: sessionmaker[Session]) -> None:
    item = competitor(factory)
    settings(factory, auto_collection_strategy="fixed_interval", auto_collection_time="09:30", auto_collection_interval_hours=4, auto_collection_daily_limit=3)
    with factory() as db:
        current = daily.get_competitor_monitoring_settings(db)
    assert daily._scheduled_times(current) == ["09:30", "13:30", "17:30"]
    assert daily._latest_occurrence(PRE, current, LOCAL) is None
    first = attempt(factory, FixedDailyState(), POST, started=PRE)
    assert first and first.competitor_ids == [item]
    finish_batch(factory, first)
    run(factory, item, POST, "success")
    second = attempt(factory, FixedDailyState(), POST + timedelta(hours=4), started=PRE)
    assert second and second.competitor_ids == [item]
    with factory() as db:
        assert "T05:30" in db.get(CollectionBatch, second.batch_id).scheduler_occurrence_key


def test_busy_runner_keeps_only_latest_fixed_point_and_next_day_is_new_occurrence(factory: sessionmaker[Session]) -> None:
    item = competitor(factory)
    settings(factory, auto_collection_times=["09:30", "13:30"], auto_collection_missed_policy="skip")
    state = FixedDailyState()
    assert attempt(factory, state, PRE) is None
    BATCH_RUNTIME.reserve([999])
    assert attempt(factory, state, POST) is None
    BATCH_RUNTIME.finish("success")
    next_point = POST + timedelta(hours=4)
    start = attempt(factory, state, next_point)
    assert start and start.competitor_ids == [item]
    with factory() as db:
        key = db.get(CollectionBatch, start.batch_id).scheduler_occurrence_key
    assert "T05:30" in key
    finish_batch(factory, start)
    tomorrow = next_point + timedelta(days=1)
    next_day = attempt(factory, state, tomorrow)
    assert next_day and next_day.competitor_ids == [item]
    with factory() as db:
        assert db.get(CollectionBatch, next_day.batch_id).scheduler_occurrence_key != key


def test_fixed_strategy_hot_switch_uses_new_schedule_on_next_check(factory: sessionmaker[Session]) -> None:
    item = competitor(factory)
    settings(factory, auto_collection_missed_policy="skip")
    state = FixedDailyState()
    assert attempt(factory, state, PRE) is None
    settings(factory, auto_collection_strategy="fixed_interval", auto_collection_time="10:00", auto_collection_interval_hours=2, auto_collection_daily_limit=3)
    assert attempt(factory, state, POST) is None
    start = attempt(factory, state, POST + timedelta(minutes=30))
    assert start and start.competitor_ids == [item]
    with factory() as db:
        assert "T02:00" in db.get(CollectionBatch, start.batch_id).scheduler_occurrence_key


def test_fixed_daily_pre_boundary_run_and_naive_utc_are_due(factory: sessionmaker[Session]) -> None:
    item = competitor(factory)
    settings(factory)
    run(factory, item, datetime(2026, 10, 6, 1, 29).replace(tzinfo=None))
    start = attempt(factory, FixedDailyState(), POST, started=POST)
    assert start and start.competitor_ids == [item]


@pytest.mark.parametrize("status", ["success", "failed"])
def test_catch_up_only_starts_remaining_after_plan(factory: sessionmaker[Session], status: str) -> None:
    first, second = competitor(factory), competitor(factory); settings(factory)
    run(factory, first, POST, status)
    start = attempt(factory, FixedDailyState(), POST, started=POST)
    assert start and start.competitor_ids == [second]


@pytest.mark.parametrize("age, expected", [(None, True), (timedelta(hours=23, minutes=59), False), (timedelta(hours=24), True)])
def test_rolling_24h_no_history_and_window_edges(factory: sessionmaker[Session], age: timedelta | None, expected: bool) -> None:
    item = competitor(factory); settings(factory, auto_collection_strategy="rolling_24h")
    if age is not None:
        run(factory, item, POST - age, "failed")
    assert (attempt(factory, FixedDailyState(), POST, started=POST) is not None) is expected


def test_scheduler_occurrence_signature_uses_due_run_facts_and_terminal_generation(factory: sessionmaker[Session]) -> None:
    item = competitor(factory)
    settings(factory, auto_collection_strategy="rolling_24h")
    state = FixedDailyState()
    first = attempt(factory, state, POST, started=POST)
    assert first is not None
    with factory() as db:
        batch = db.get(CollectionBatch, first.batch_id)
        assert batch is not None and batch.scheduler_occurrence_key is not None
        first_key = batch.scheduler_occurrence_key
        assert first_key.startswith("rolling_24h:rolling_24h:") and first_key.endswith(":1")
        batch.lifecycle_status = "terminal"
        batch.outcome_code = "interrupted"
        db.commit()
    second = attempt(factory, state, POST + timedelta(minutes=1), started=POST)
    assert second is not None
    with factory() as db:
        batch = db.get(CollectionBatch, second.batch_id)
        assert batch is not None and batch.scheduler_occurrence_key is not None
        assert batch.scheduler_occurrence_key.rsplit(":", 1)[0] == first_key.rsplit(":", 1)[0]
        assert batch.scheduler_occurrence_key.endswith(":2")


def test_disabled_does_not_reserve_or_stop_existing_batch(factory: sessionmaker[Session]) -> None:
    competitor(factory); settings(factory, auto_collection_enabled=False)
    BATCH_RUNTIME.reserve([999])
    assert attempt(factory, FixedDailyState(), POST) is None
    assert BATCH_RUNTIME.is_busy()
    BATCH_RUNTIME.finish("success")


def test_preparation_lookup_error_does_not_leak_reservation(factory, monkeypatch):
    competitor(factory)
    original = Session.scalars
    def fail(self, statement, *args, **kwargs):
        if str(statement).startswith("SELECT collection_batches.scheduler_occurrence_key "):
            raise OperationalError("occurrence lookup", {}, Exception("database is locked"))
        return original(self, statement, *args, **kwargs)
    monkeypatch.setattr(Session, "scalars", fail)
    with pytest.raises(OperationalError):
        prepare_auto_batch(factory, now=POST)
    assert not BATCH_RUNTIME.is_busy()
    with factory() as db:
        assert db.scalars(select(CollectionBatch)).all() == []


def test_preparation_does_not_reload_committed_plan_before_dispatch(factory):
    competitor(factory)
    factory.configure(expire_on_commit=True)
    engine = factory.kw["bind"]
    def no_reload(connection, cursor, statement, parameters, context, executemany):
        if "WHERE collection_batches.id =" in statement and BATCH_RUNTIME.runner_active:
            raise OperationalError(statement, parameters, Exception("post-commit read failed"))
    event.listen(engine, "before_cursor_execute", no_reload)
    try:
        result = prepare_auto_batch(factory, now=POST)
        assert result is not None and BATCH_RUNTIME.batch_id == result.batch_id
    finally:
        event.remove(engine, "before_cursor_execute", no_reload)
    with factory() as db:
        assert db.get(CollectionBatch, result.batch_id).lifecycle_status == "created"


def test_preparation_write_failure_releases_reservation_and_plan(factory, monkeypatch):
    competitor(factory)
    original = daily.create_collection_batch
    def fail(db, *args, **kwargs):
        assert BATCH_RUNTIME.is_busy()
        # Flush the real plan and items, then fail before commit.
        with monkeypatch.context() as patch:
            patch.setattr(db, "commit", lambda: (_ for _ in ()).throw(OperationalError("commit", {}, Exception("database is locked"))))
            return original(db, *args, **kwargs)
    monkeypatch.setattr(daily, "create_collection_batch", fail)
    with pytest.raises(OperationalError):
        prepare_auto_batch(factory, now=POST)
    assert not BATCH_RUNTIME.is_busy()
    with factory() as db:
        assert db.scalars(select(CollectionBatch)).all() == []


def test_skip_late_start_and_post_plan_enable_do_not_catch_up(factory: sessionmaker[Session]) -> None:
    item = competitor(factory); settings(factory, auto_collection_missed_policy="skip")
    assert attempt(factory, FixedDailyState(), POST, started=POST) is None
    state = FixedDailyState(); settings(factory, auto_collection_strategy="rolling_24h")
    assert attempt(factory, state, POST, started=PRE) is not None
    settings(factory, auto_collection_strategy="fixed_daily", auto_collection_missed_policy="skip")
    assert attempt(factory, state, POST, started=PRE) is None
    assert item


def test_startup_disabled_then_enable_after_plan_skips_today(factory: sessionmaker[Session]) -> None:
    item = competitor(factory)
    settings(factory, auto_collection_enabled=False, auto_collection_missed_policy="skip")
    state = FixedDailyState()
    assert attempt(factory, state, PRE) is None
    settings(factory, auto_collection_enabled=True)
    assert attempt(factory, state, POST) is None
    tomorrow = POST + timedelta(days=1)
    start = attempt(factory, state, tomorrow)
    assert start and start.competitor_ids == [item]


def test_skip_pending_retries_when_busy_and_recomputes_formal_attempt(factory: sessionmaker[Session]) -> None:
    item = competitor(factory); settings(factory, auto_collection_missed_policy="skip")
    state = FixedDailyState()
    assert attempt(factory, state, PRE) is None
    BATCH_RUNTIME.reserve([999])
    assert attempt(factory, state, POST) is None
    BATCH_RUNTIME.finish("success")
    start = attempt(factory, state, POST)
    assert start and start.competitor_ids == [item]
    run(factory, item, POST)
    assert attempt(factory, state, POST) is None


@pytest.mark.parametrize(
    "change, checked_at, expected",
    [
        ({"auto_collection_enabled": False}, POST, False),
        ({"auto_collection_strategy": "rolling_24h"}, POST, True),
        ({"auto_collection_time": "10:00", "auto_collection_times": ["10:00"]}, POST, False),
        ({"auto_collection_missed_policy": "skip"}, POST, False),
    ],
)
def test_stale_pending_is_cleared_on_settings_change(factory: sessionmaker[Session], change: dict[str, object], checked_at: datetime, expected: bool) -> None:
    competitor(factory); settings(factory)
    state = FixedDailyState(); assert attempt(factory, state, PRE) is None
    BATCH_RUNTIME.reserve([999]); assert attempt(factory, state, POST) is None; BATCH_RUNTIME.finish("success")
    settings(factory, **change)
    result = attempt(factory, state, checked_at)
    assert (result is not None) is expected


def test_reenable_skip_after_plan_and_next_day_do_not_revive_old_pending(factory: sessionmaker[Session]) -> None:
    competitor(factory); settings(factory, auto_collection_missed_policy="skip")
    state = FixedDailyState(); assert attempt(factory, state, PRE) is None
    BATCH_RUNTIME.reserve([999]); assert attempt(factory, state, POST) is None; BATCH_RUNTIME.finish("success")
    settings(factory, auto_collection_enabled=False); assert attempt(factory, state, POST) is None
    settings(factory, auto_collection_enabled=True); assert attempt(factory, state, POST) is None
    tomorrow = POST + timedelta(days=1)
    start = attempt(factory, state, tomorrow)
    assert start is not None


def test_rolling_24h_and_real_slot_race_recheck(factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch) -> None:
    item = competitor(factory); settings(factory, auto_collection_strategy="rolling_24h")
    state = FixedDailyState(); calls = 0
    real_slot = daily.acquire_collection_slot

    def manual_between_precheck_and_reservation(**kwargs: object) -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            with factory() as db:
                # This is the existing manual collector: it takes the same slot and commits CollectionRun.
                product = ProductData(offer_id="100", title="manual", shop_name="shop", main_image_url=None, price_min=Decimal("1"), price_max=Decimal("1"), product_status="active", collection_source="html", captured_at=POST, skus=[])
                monkeypatch.setattr("app.collection.service.collect_1688_product", lambda *_args, **_kwargs: product)
                collect_competitor(db, item)
        return real_slot(**kwargs)

    monkeypatch.setattr(daily, "acquire_collection_slot", manual_between_precheck_and_reservation)
    assert attempt(factory, state, POST) is None
    with factory() as db:
        assert db.query(CollectionRun).filter_by(competitor_id=item).count() == 1


@pytest.mark.parametrize("change", [{"auto_collection_time": "10:00", "auto_collection_times": ["10:00"]}, {"auto_collection_missed_policy": "skip"}])
def test_locked_eligibility_uses_settings_changed_after_precheck(factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch, change: dict[str, object]) -> None:
    competitor(factory); settings(factory)
    real_slot = daily.acquire_collection_slot
    changed = False

    def change_before_slot(**kwargs: object) -> bool:
        nonlocal changed
        if not changed:
            changed = True
            settings(factory, **change)
        return real_slot(**kwargs)

    monkeypatch.setattr(daily, "acquire_collection_slot", change_before_slot)
    assert attempt(factory, FixedDailyState(), POST, started=POST) is None
    assert not BATCH_RUNTIME.is_busy()


def test_fixed_daily_real_slot_race_rechecks_collection_run(factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch) -> None:
    item = competitor(factory); settings(factory)
    real_slot = daily.acquire_collection_slot
    ran_manual = False

    def manual_before_slot(**kwargs: object) -> bool:
        nonlocal ran_manual
        if not ran_manual:
            ran_manual = True
            with factory() as db:
                product = ProductData(offer_id="100", title="manual", shop_name="shop", main_image_url=None, price_min=Decimal("1"), price_max=Decimal("1"), product_status="active", collection_source="html", captured_at=POST, skus=[])
                monkeypatch.setattr("app.collection.service.collect_1688_product", lambda *_args, **_kwargs: product)
                collect_competitor(db, item)
        return real_slot(**kwargs)

    monkeypatch.setattr(daily, "acquire_collection_slot", manual_before_slot)
    assert attempt(factory, FixedDailyState(), POST, started=POST) is None
    with factory() as db:
        assert db.query(CollectionRun).filter_by(competitor_id=item).count() == 1


def test_locked_disable_then_reenable_skip_cannot_reuse_preplan_lifecycle(factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch) -> None:
    competitor(factory); settings(factory, auto_collection_missed_policy="skip")
    state = FixedDailyState(); assert attempt(factory, state, PRE) is None
    real_slot = daily.acquire_collection_slot
    disabled = False
    def disable_before_slot(**kwargs: object) -> bool:
        nonlocal disabled
        if not disabled:
            disabled = True; settings(factory, auto_collection_enabled=False)
        return real_slot(**kwargs)
    monkeypatch.setattr(daily, "acquire_collection_slot", disable_before_slot)
    assert attempt(factory, state, POST) is None
    settings(factory, auto_collection_enabled=True)
    assert attempt(factory, state, POST) is None
