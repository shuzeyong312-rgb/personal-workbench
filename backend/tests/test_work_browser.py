import asyncio
from contextlib import contextmanager
from threading import Event

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app import work_browser as wb


def test_lease_rejects_second_owner_and_releases(tmp_path):
    first = wb.acquire_backend_lease(tmp_path / "profile")
    try:
        try:
            wb.acquire_backend_lease(tmp_path / "profile")
            assert False, "second owner acquired lease"
        except RuntimeError:
            pass
    finally:
        first.close()
    wb.acquire_backend_lease(tmp_path / "profile").close()


def test_management_holds_collection_lock_until_close(monkeypatch):
    started, end = Event(), Event()

    class Page:
        def wait_for_timeout(self, _):
            end.wait(.02)
            if end.is_set():
                context.callback(None)

    class Context:
        pages = [Page()]
        def on(self, _, callback):
            self.callback = callback
        def close(self):
            self.callback(None)

    context = Context()
    @contextmanager
    def playwright():
        yield object()
    def launch(_):
        started.set()
        return context
    monkeypatch.setattr(wb, "sync_playwright", playwright)
    monkeypatch.setattr(wb, "_launch_context", launch)
    manager = wb.WorkBrowser()
    manager.open()
    assert started.wait(2)
    manager.open()
    assert not wb.acquire_collection_slot()
    end.set()
    manager.thread.join(2)
    assert not manager.thread.is_alive()
    assert manager.snapshot()["status"] == "idle"
    assert wb.acquire_collection_slot()
    wb.COLLECTION_LOCK.release()
    asyncio.run(manager.shutdown())


def test_post_rejects_cross_site_and_allows_expected_origin(monkeypatch):
    app = FastAPI()
    app.include_router(wb.router)
    monkeypatch.setenv("PERSONAL_WORKBENCH_FRONTEND_ORIGIN", "http://127.0.0.1:5000")
    monkeypatch.setattr(wb.WORK_BROWSER, "open", lambda: None)
    client = TestClient(app, base_url="http://127.0.0.1:8200")
    headers = {"origin": "http://127.0.0.1:5000", "content-type": "application/json", "x-workbench-request": "work-browser"}
    assert client.post("/api/work-browser", content="{}", headers=headers).status_code == 200
    assert client.post("/api/work-browser", content="{}", headers={**headers, "origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/work-browser", content="{}", headers={k: v for k, v in headers.items() if k != "origin"}).status_code == 403
    assert client.post("/api/work-browser", content="{}", headers={**headers, "host": "evil.example"}).status_code == 403
    assert client.post("/api/work-browser", content="{}", headers={**headers, "content-type": "text/plain"}).status_code == 403
    assert client.post("/api/work-browser", content="{}", headers={k: v for k, v in headers.items() if k != "x-workbench-request"}).status_code == 403
    assert client.options("/api/work-browser", headers={"origin": "https://evil.example", "access-control-request-method": "POST", "access-control-request-headers": "x-workbench-request"}).status_code != 200


def test_launch_failure_releases_slot_and_allows_retry(monkeypatch):
    @contextmanager
    def playwright():
        yield object()
    attempts = []
    def fail(_):
        attempts.append(True)
        raise RuntimeError("private error")
    monkeypatch.setattr(wb, "sync_playwright", playwright)
    monkeypatch.setattr(wb, "_launch_context", fail)
    manager = wb.WorkBrowser()
    manager.open()
    manager.thread.join(2)
    assert not manager.thread.is_alive()
    assert manager.snapshot()["status"] == "idle"
    assert "private error" not in manager.snapshot()["message"]
    assert wb.acquire_collection_slot()
    wb.COLLECTION_LOCK.release()
    manager.open()
    manager.thread.join(2)
    assert not manager.thread.is_alive()
    assert manager.snapshot()["status"] == "idle"
    assert len(attempts) == 2


def test_unconfirmed_context_close_keeps_slot_until_shutdown(monkeypatch):
    @contextmanager
    def playwright():
        yield object()
    class Context:
        pages = []
        def on(self, *_):
            pass
        def close(self):
            raise RuntimeError("close failed")
    monkeypatch.setattr(wb, "sync_playwright", playwright)
    monkeypatch.setattr(wb, "_launch_context", lambda _: Context())
    manager = wb.WorkBrowser()
    manager.open()
    for _ in range(100):
        if manager.snapshot()["status"] == "unknown":
            break
        Event().wait(.01)
    assert manager.snapshot()["status"] == "unknown"
    assert not wb.acquire_collection_slot()
    asyncio.run(manager.shutdown())
    assert wb.acquire_collection_slot()
    wb.COLLECTION_LOCK.release()


def test_lifespan_releases_lease_and_stops_browser_when_scheduler_disabled(tmp_path, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "_project_root", lambda: tmp_path)
    monkeypatch.setenv("PERSONAL_WORKBENCH_DISABLE_SCHEDULER", "1")
    monkeypatch.setattr(main, "recover_interrupted_batches", lambda _: None)
    monkeypatch.setattr(main, "recover_customer_reach_tasks", lambda _: None)
    calls = []
    async def stopped():
        calls.append("browser")
    monkeypatch.setattr(main.WORK_BROWSER, "shutdown", stopped)
    async def exercise():
        app = FastAPI()
        async with main.lifespan(app):
            try:
                wb.acquire_backend_lease(tmp_path / ".browser-profile")
                assert False, "lease not held during lifespan"
            except RuntimeError:
                pass
        wb.acquire_backend_lease(tmp_path / ".browser-profile").close()
    asyncio.run(exercise())
    assert calls == ["browser"]


@pytest.mark.parametrize("failing_shutdown", ["batch", "browser"])
def test_lifespan_releases_lease_when_shutdown_fails(tmp_path, monkeypatch, failing_shutdown):
    from app import main
    monkeypatch.setattr(main, "_project_root", lambda: tmp_path)
    monkeypatch.setenv("PERSONAL_WORKBENCH_DISABLE_SCHEDULER", "1")
    monkeypatch.setattr(main, "recover_interrupted_batches", lambda _: None)
    monkeypatch.setattr(main, "recover_customer_reach_tasks", lambda _: None)
    calls = []
    async def stop_batch():
        calls.append("batch")
        if failing_shutdown == "batch":
            raise RuntimeError("batch shutdown failed")
    async def stop_browser():
        calls.append("browser")
        if failing_shutdown == "browser":
            raise RuntimeError("browser shutdown failed")
    monkeypatch.setattr(main, "shutdown_batch_runner", stop_batch)
    monkeypatch.setattr(main.WORK_BROWSER, "shutdown", stop_browser)
    async def exercise():
        app = FastAPI()
        with pytest.raises(RuntimeError, match=failing_shutdown + " shutdown failed"):
            async with main.lifespan(app):
                pass
        assert app.state.browser_lease is None
        wb.acquire_backend_lease(tmp_path / ".browser-profile").close()
    asyncio.run(exercise())
    assert calls == ["batch", "browser"]
