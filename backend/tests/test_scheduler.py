import asyncio
import sqlite3
from datetime import datetime, timezone
from threading import Event

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main
from app.collection.daily import AutoBatchStart
from app.collection.service import BATCH_RUNTIME, BatchConfig
from app.models import Base, CollectionBatch


def test_lifespan_starts_and_cancels_scheduler(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    monkeypatch.delenv("PERSONAL_WORKBENCH_DISABLE_SCHEDULER", raising=False)
    monkeypatch.setattr(main, "recover_interrupted_batches", lambda _session_factory: 0)
    async def scheduler(stop: asyncio.Event, _thread: Event) -> None:
        events.append("started"); await stop.wait(); events.append("stopped")
    monkeypatch.setattr(main, "_daily_collection_loop", scheduler)
    with TestClient(main.app): assert events == ["started"]
    assert events == ["started", "stopped"]


def test_disabled_scheduler_still_runs_interrupted_batch_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setenv("PERSONAL_WORKBENCH_DISABLE_SCHEDULER", "1")
    monkeypatch.setattr(main, "recover_interrupted_batches", lambda value: calls.append(value))
    main.app.state.collection_session_factory = factory
    try:
        with TestClient(main.app):
            pass
        assert calls == [factory]
    finally:
        main.app.state.collection_session_factory = None
        engine.dispose()


def test_scheduler_starts_reserved_batch_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[object] = []
    batch = AutoBatchStart([7], BatchConfig(), 3, 14)
    async def fake_thread(*_args: object, **_kwargs: object) -> AutoBatchStart: return batch
    monkeypatch.setattr(main.asyncio, "to_thread", fake_thread)
    monkeypatch.setattr(main, "start_batch_task", lambda *args, **kwargs: started.append((args, kwargs)))
    async def run() -> None:
        stop = asyncio.Event(); thread = Event(); task = asyncio.create_task(main._daily_collection_loop(stop, thread))
        while not started: await asyncio.sleep(0)
        stop.set(); thread.set(); await asyncio.wait_for(task, .1)
    asyncio.run(run())
    assert started[0][0][1] == [7]
    assert started[0][1]["batch_reservation"] == 3
    assert started[0][1]["persisted_batch_id"] == 14


def test_scheduler_dispatch_failure_closes_created_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        batch = CollectionBatch(task_id="dispatch-failure", trigger_kind="scheduled", created_at=datetime.now(timezone.utc), lifecycle_status="created", settings_snapshot={}, planned_products=0)
        db.add(batch); db.commit(); batch_id = batch.id
    start = AutoBatchStart([], BatchConfig(), 3, batch_id)
    starts = 0
    async def fake_thread(*_args: object, **_kwargs: object) -> AutoBatchStart | None:
        nonlocal starts
        starts += 1
        return start if starts == 1 else None
    monkeypatch.setattr(main, "_session_factory", factory)
    monkeypatch.setattr(main.asyncio, "to_thread", fake_thread)
    monkeypatch.setattr(main, "start_batch_task", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("runner dispatch failed")))
    async def run() -> None:
        stop = asyncio.Event(); thread = Event(); task = asyncio.create_task(main._daily_collection_loop(stop, thread))
        while starts == 0: await asyncio.sleep(0)
        await asyncio.sleep(0); thread.set(); stop.set(); await asyncio.wait_for(task, .1)
    try:
        asyncio.run(run())
        with factory() as db:
            batch = db.get(CollectionBatch, batch_id)
            assert batch is not None and batch.lifecycle_status == "terminal" and batch.outcome_code == "infrastructure_error"
    finally:
        engine.dispose()


def test_scheduler_stop_wakes_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "prepare_auto_batch", lambda *_args, **_kwargs: None)
    async def run() -> None:
        stop = asyncio.Event(); thread = Event(); task = asyncio.create_task(main._daily_collection_loop(stop, thread))
        await asyncio.sleep(0); stop.set(); thread.set(); await asyncio.wait_for(task, .1)
    asyncio.run(run())


def test_scheduler_recovers_after_real_sqlite_lock(monkeypatch, tmp_path, caplog):
    path = tmp_path / "scheduler.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}", connect_args={"check_same_thread": False, "timeout": .01})
    Base.metadata.create_all(engine)
    monkeypatch.setattr(main, "_session_factory", sessionmaker(bind=engine))
    lock = sqlite3.connect(path)
    lock.execute("BEGIN EXCLUSIVE")
    waits = []
    async def wait(stop, timeout):
        waits.append(timeout)
        lock.rollback()
        return len(waits) == 2
    monkeypatch.setattr(main, "_wait_for_stop", wait)
    try:
        asyncio.run(main._daily_collection_loop(asyncio.Event(), Event()))
        assert waits == [60, 60]
        assert "locked" in caplog.text.lower()
    finally:
        lock.close()
        engine.dispose()


def test_failed_scheduler_still_shuts_down_runner(monkeypatch):
    events = []
    monkeypatch.delenv("PERSONAL_WORKBENCH_DISABLE_SCHEDULER", raising=False)
    monkeypatch.setattr(main, "recover_interrupted_batches", lambda factory: 0)
    def fail(*args, **kwargs):
        raise RuntimeError("unexpected preparation failure")
    monkeypatch.setattr(main, "prepare_auto_batch", fail)
    async def shutdown():
        events.append("shutdown")
    monkeypatch.setattr(main, "shutdown_batch_runner", shutdown)
    async def run():
        with pytest.raises(RuntimeError, match="unexpected preparation failure"):
            async with main.lifespan(main.app):
                await asyncio.sleep(0)
    asyncio.run(run())
    assert events == ["shutdown"]


def test_dispatch_cleanup_retries_locked_database_before_new_plan(monkeypatch, tmp_path):
    starts, cleanups, waits = [], [], []
    engine = create_engine(f"sqlite:///{(tmp_path/'dispatch.db').as_posix()}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        batch = CollectionBatch(task_id="cleanup-retry", trigger_kind="scheduled", created_at=datetime.now(timezone.utc), lifecycle_status="created", settings_snapshot={}, planned_products=0)
        db.add(batch); db.commit(); batch_id = batch.id
    start = AutoBatchStart([], BatchConfig(), 3, batch_id)
    monkeypatch.setattr(main, "_session_factory", factory)
    def prepare(*args, **kwargs):
        starts.append(True)
        assert BATCH_RUNTIME.reserve([])
        return start
    monkeypatch.setattr(main, "prepare_auto_batch", prepare)
    monkeypatch.setattr(main, "start_batch_task", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("dispatch failed")))
    original_cleanup = main.fail_created_batch
    def cleanup(factory, batch_id):
        assert BATCH_RUNTIME.is_busy() and not BATCH_RUNTIME.reserve([999])
        cleanups.append(batch_id)
        if len(cleanups) == 1:
            original = sqlite3.OperationalError("database is locked")
            original.sqlite_errorcode = sqlite3.SQLITE_BUSY
            raise OperationalError("cleanup", {}, original)
        return original_cleanup(factory, batch_id)
    monkeypatch.setattr(main, "fail_created_batch", cleanup)
    async def wait(stop, timeout):
        waits.append(timeout)
        return len(waits) == 2
    monkeypatch.setattr(main, "_wait_for_stop", wait)
    try:
        asyncio.run(main._daily_collection_loop(asyncio.Event(), Event()))
        assert cleanups == [batch_id, batch_id]
        assert len(starts) == 1
        assert not BATCH_RUNTIME.is_busy()
        with factory() as db:
            batch = db.get(CollectionBatch, batch_id)
            assert batch.lifecycle_status == "terminal" and batch.outcome_code == "infrastructure_error"
    finally:
        BATCH_RUNTIME.finish("success")
        engine.dispose()


def test_nonlocking_database_error_is_not_retried(monkeypatch):
    def fail(*args, **kwargs):
        original = sqlite3.OperationalError("no such table: system_settings")
        original.sqlite_errorcode = sqlite3.SQLITE_ERROR
        raise OperationalError("read settings", {}, original)
    monkeypatch.setattr(main, "prepare_auto_batch", fail)
    with pytest.raises(OperationalError):
        asyncio.run(main._daily_collection_loop(asyncio.Event(), Event()))
