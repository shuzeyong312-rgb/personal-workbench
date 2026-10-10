import asyncio
from threading import Event

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.collection.daily import AutoBatchStart
from app.collection.service import BatchConfig


def test_lifespan_starts_and_cancels_scheduler(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    async def scheduler(stop: asyncio.Event, _thread: Event) -> None:
        events.append("started"); await stop.wait(); events.append("stopped")
    monkeypatch.setattr(main, "_daily_collection_loop", scheduler)
    with TestClient(main.app): assert events == ["started"]
    assert events == ["started", "stopped"]


def test_scheduler_starts_reserved_batch_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[object] = []
    batch = AutoBatchStart([7], BatchConfig(), 3)
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


def test_scheduler_stop_wakes_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "prepare_auto_batch", lambda *_args, **_kwargs: None)
    async def run() -> None:
        stop = asyncio.Event(); thread = Event(); task = asyncio.create_task(main._daily_collection_loop(stop, thread))
        await asyncio.sleep(0); stop.set(); thread.set(); await asyncio.wait_for(task, .1)
    asyncio.run(run())
