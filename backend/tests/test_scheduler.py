import asyncio
from threading import Event
import time

import pytest
from fastapi.testclient import TestClient

import app.main as main


def test_lifespan_starts_and_cancels_scheduler(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    async def fake_scheduler(stop_event: asyncio.Event, _thread_stop_event: Event) -> None:
        events.append("started")
        await stop_event.wait()
        events.append("stopped")

    monkeypatch.setattr(main, "_daily_collection_loop", fake_scheduler)

    with TestClient(main.app):
        assert events == ["started"]

    assert events == ["started", "stopped"]


def test_scheduler_delays_then_runs_cycle_in_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    thread_calls: list[tuple[object, tuple[object, ...], dict[str, object]]] = []
    cycle_finished = asyncio.Event()
    monkeypatch.setattr(main, "DAILY_COLLECTION_INITIAL_DELAY_SECONDS", 0.01)

    async def fake_to_thread(function: object, *args: object, **kwargs: object) -> None:
        thread_calls.append((function, args, kwargs))
        cycle_finished.set()

    monkeypatch.setattr(main.asyncio, "to_thread", fake_to_thread)

    async def run_scheduler() -> None:
        stop_event = asyncio.Event()
        thread_stop_event = Event()
        task = asyncio.create_task(main._daily_collection_loop(stop_event, thread_stop_event))
        await cycle_finished.wait()
        stop_event.set()
        thread_stop_event.set()
        await asyncio.wait_for(task, timeout=0.1)

    asyncio.run(run_scheduler())

    assert len(thread_calls) == 1
    assert thread_calls[0][0:2] == (main.run_daily_collection_cycle, (main._session_factory,))
    assert isinstance(thread_calls[0][2]["stop_event"], Event)


def test_scheduler_stop_wakes_initial_wait_immediately() -> None:
    async def run_scheduler() -> None:
        stop_event = asyncio.Event()
        thread_stop_event = Event()
        task = asyncio.create_task(main._daily_collection_loop(stop_event, thread_stop_event))
        await asyncio.sleep(0)
        stop_event.set()
        thread_stop_event.set()
        await asyncio.wait_for(task, timeout=0.1)

    asyncio.run(run_scheduler())


def test_shutdown_waits_for_current_thread_runner_then_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()
    release = Event()
    monkeypatch.setattr(main, "DAILY_COLLECTION_INITIAL_DELAY_SECONDS", 0.01)

    def blocking_runner(_session_factory: object, *, stop_event: Event) -> None:
        started.set()
        while not release.is_set():
            time.sleep(0.001)
        assert stop_event.is_set()

    monkeypatch.setattr(main, "run_daily_collection_cycle", blocking_runner)

    async def run_scheduler() -> None:
        stop_event = asyncio.Event()
        thread_stop_event = Event()
        task = asyncio.create_task(main._daily_collection_loop(stop_event, thread_stop_event))
        while not started.is_set():
            await asyncio.sleep(0.001)
        stop_event.set()
        thread_stop_event.set()
        await asyncio.sleep(0.01)
        assert not task.done()
        release.set()
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(run_scheduler())
