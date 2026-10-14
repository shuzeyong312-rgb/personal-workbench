import asyncio
from datetime import datetime, timezone
from threading import Event

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main
from app.collection.daily import AutoBatchStart
from app.collection.service import BatchConfig
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
