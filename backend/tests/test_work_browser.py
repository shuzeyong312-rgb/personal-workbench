import asyncio
from contextlib import contextmanager
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app import work_browser as wb
from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError


class FakeContext:
    @property
    def browser(self):
        context = self
        class Session:
            def send(self, method):
                if method == "SystemInfo.getProcessInfo":
                    raise RuntimeError("fake browser has no OS process")
                try:
                    context.wait_for_event("close", timeout=250)
                except PlaywrightTimeoutError:
                    pass
                return {}
            def detach(self):
                pass
        return SimpleNamespace(new_browser_cdp_session=Session)


def test_driver_failure_releases_slot_after_owned_chrome_exits_and_allows_reopen(monkeypatch):
    exited = Event()
    attempts = []
    class Process:
        def wait(self, timeout):
            return exited.wait(timeout / 1000)
        def close(self):
            pass
    class Page:
        def wait_for_timeout(self, _):
            raise Exception("Connection closed while reading from the driver")
    class Context(FakeContext):
        pages = [Page()]
        def wait_for_event(self, _, timeout):
            raise Exception("Connection closed while reading from the driver")
        def on(self, *_):
            pass
        def close(self):
            raise Exception("driver terminated")
    @contextmanager
    def playwright():
        yield object()
    def launch(_, **kwargs):
        attempts.append(True)
        return Context()
    monkeypatch.setattr(wb, "sync_playwright", playwright)
    monkeypatch.setattr(wb, "_launch_context", launch)
    monkeypatch.setattr(wb, "watch_browser_process", lambda _: Process())
    monkeypatch.setattr(wb, "show_work_browser_window", lambda *_: None)
    manager = wb.WorkBrowser()
    try:
        manager.open()
        deadline = monotonic() + 2
        while manager.snapshot()["status"] != "unknown" and monotonic() < deadline:
            sleep(.01)
        assert manager.snapshot()["status"] == "unknown"
        assert not wb.acquire_collection_slot()
        exited.set()
        manager.thread.join(2)
        assert not manager.thread.is_alive()
        assert manager.snapshot()["status"] == "idle"
        assert wb.acquire_collection_slot()
        wb.COLLECTION_LOCK.release()
        manager.open()
        manager.thread.join(2)
        assert len(attempts) == 2
        assert manager.snapshot()["status"] == "idle"
    finally:
        asyncio.run(manager.shutdown())


def test_closing_one_page_does_not_close_managed_browser(monkeypatch):
    waiting = Event()
    class Page:
        url = "about:blank"
        def __init__(self):
            self.closed = False
        def is_closed(self):
            return self.closed
        def wait_for_timeout(self, _):
            if self is first and not self.closed:
                self.closed = True
                context.pages.remove(self)
                raise PlaywrightError("Target page has been closed")
            waiting.set()
            sleep(.01)
    class Context(FakeContext):
        def __init__(self):
            self.pages = [first, second]
            self.close_calls = 0
        def wait_for_event(self, _, timeout):
            if first in self.pages:
                first.closed = True
                self.pages.remove(first)
            waiting.set()
            sleep(.01)
            raise PlaywrightTimeoutError("timeout")
        def on(self, _, callback):
            self.callback = callback
        def close(self):
            self.close_calls += 1
            self.callback(None)
    first, second = Page(), Page()
    context = Context()
    @contextmanager
    def playwright():
        yield object()
    monkeypatch.setattr(wb, "sync_playwright", playwright)
    monkeypatch.setattr(wb, "_launch_context", lambda _, **kwargs: context)
    monkeypatch.setattr(wb, "show_work_browser_window", lambda *_: None)
    manager = wb.WorkBrowser()
    try:
        manager.open()
        assert waiting.wait(1), "closing a single page stopped the management loop"
        assert manager.snapshot()["status"] == "managing"
        assert context.close_calls == 0
        assert not wb.acquire_collection_slot()
    finally:
        asyncio.run(manager.shutdown())


def test_temporarily_empty_pages_wait_for_context_close(monkeypatch):
    entered = Event()
    class Context(FakeContext):
        pages = []
        close_calls = 0
        def on(self, _, callback):
            self.callback = callback
        def wait_for_event(self, _, timeout):
            entered.set()
            sleep(.01)
            raise PlaywrightTimeoutError("timeout")
        def close(self):
            self.close_calls += 1
            self.callback(None)
    context = Context()
    @contextmanager
    def playwright():
        yield object()
    monkeypatch.setattr(wb, "sync_playwright", playwright)
    monkeypatch.setattr(wb, "_launch_context", lambda _, **kwargs: context)
    manager = wb.WorkBrowser()
    try:
        manager.open()
        assert entered.wait(1)
        assert manager.snapshot()["status"] == "managing"
        assert context.close_calls == 0
        assert not wb.acquire_collection_slot()
    finally:
        asyncio.run(manager.shutdown())
    assert context.close_calls == 1


@pytest.mark.parametrize("bounds, reset", [
    ({"left": -32000, "top": -32000, "width": 1200, "height": 800}, True),
    ({"left": 100, "top": 80, "width": 800, "height": 600}, False),
    ({"left": 100, "top": 80, "width": 2000, "height": 600}, True),
])
def test_window_restores_and_moves_only_outside_visible_area(monkeypatch, bounds, reset):
    monkeypatch.setattr(wb.os, "name", "posix")
    calls = []
    class Page:
        def evaluate(self, _):
            return {"left": 0, "top": 0, "width": 1024, "height": 768}
        def bring_to_front(self):
            calls.append(("front", None))
    class CDP:
        def send(self, method, params=None):
            calls.append((method, params))
            return {"windowId": 7, "bounds": bounds}
        def detach(self):
            pass
    class Context(FakeContext):
        def new_cdp_session(self, _):
            return CDP()
    wb.show_work_browser_window(Context(), Page())
    changes = [params["bounds"] for method, params in calls if method == "Browser.setWindowBounds"]
    assert changes[0] == {"windowState": "normal"}
    assert len(changes) == (2 if reset else 1)
    if reset:
        assert changes[1] == {"left": 0, "top": 0, "width": 1024, "height": 768}
    assert calls[-1][0] == "front"


def test_reopen_and_extensions_use_existing_browser_thread(monkeypatch):
    events = []
    class Page:
        url = "about:blank"
        def wait_for_timeout(self, _):
            sleep(.01)
        def goto(self, url):
            self.url = url
            events.append(("navigate", url))
    class Context(FakeContext):
        def __init__(self):
            self.pages = [Page()]
        def wait_for_event(self, _, timeout):
            sleep(.01)
            raise PlaywrightTimeoutError("timeout")
        def on(self, _, callback):
            self.callback = callback
        def new_page(self):
            page = Page()
            self.pages.append(page)
            return page
        def close(self):
            self.callback(None)
    context = Context()
    @contextmanager
    def playwright():
        yield object()
    def focus(_, page):
        events.append(("focus", page.url))
    monkeypatch.setattr(wb, "sync_playwright", playwright)
    monkeypatch.setattr(wb, "_launch_context", lambda _, **kwargs: context)
    monkeypatch.setattr(wb, "show_work_browser_window", focus)
    manager = wb.WorkBrowser()
    try:
        manager.open()
        deadline = monotonic() + 2
        while len(events) < 1 and monotonic() < deadline:
            sleep(.01)
        assert events == [("focus", "about:blank")]
        manager.open()
        deadline = monotonic() + 2
        while len(events) < 2 and monotonic() < deadline:
            sleep(.01)
        assert events.count(("focus", "about:blank")) == 2
        manager.open(extensions=True)
        deadline = monotonic() + 2
        while len(events) < 4 and monotonic() < deadline:
            sleep(.01)
        assert events[-2:] == [("navigate", "chrome://extensions/"), ("focus", "chrome://extensions/")]
        manager.open(extensions=True)
        deadline = monotonic() + 2
        while len(events) < 5 and monotonic() < deadline:
            sleep(.01)
        assert events[-1] == ("focus", "chrome://extensions/")
        assert len(context.pages) == 2
        assert not wb.acquire_collection_slot()
    finally:
        asyncio.run(manager.shutdown())


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

    class Context(FakeContext):
        pages = [Page()]
        def wait_for_event(self, _, timeout):
            self.pages[0].wait_for_timeout(timeout)
            if not end.is_set():
                raise PlaywrightTimeoutError("timeout")
        def on(self, _, callback):
            self.callback = callback
        def close(self):
            self.callback(None)

    context = Context()
    @contextmanager
    def playwright():
        yield object()
    def launch(_, **kwargs):
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
    requests = []
    monkeypatch.setattr(wb.WORK_BROWSER, "open", lambda **kwargs: requests.append(kwargs))
    client = TestClient(app, base_url="http://127.0.0.1:8200")
    headers = {"origin": "http://127.0.0.1:5000", "content-type": "application/json", "x-workbench-request": "work-browser"}
    assert client.post("/api/work-browser", content="{}", headers=headers).status_code == 200
    assert client.post("/api/work-browser/extensions", content="{}", headers=headers).status_code == 200
    assert requests == [{}, {"extensions": True}]
    assert client.post("/api/work-browser", content="{}", headers={**headers, "origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/work-browser", content="{}", headers={k: v for k, v in headers.items() if k != "origin"}).status_code == 403
    assert client.post("/api/work-browser", content="{}", headers={**headers, "host": "evil.example"}).status_code == 403
    assert client.post("/api/work-browser", content="{}", headers={**headers, "content-type": "text/plain"}).status_code == 403
    assert client.post("/api/work-browser/extensions", content="{}", headers={**headers, "origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/work-browser/extensions", content='{"url":"https://evil.example"}', headers=headers).status_code == 403
    assert client.post("/api/work-browser", content="{}", headers={k: v for k, v in headers.items() if k != "x-workbench-request"}).status_code == 403
    assert client.options("/api/work-browser", headers={"origin": "https://evil.example", "access-control-request-method": "POST", "access-control-request-headers": "x-workbench-request"}).status_code != 200


def test_launch_failure_releases_slot_and_allows_retry(monkeypatch):
    @contextmanager
    def playwright():
        yield object()
    attempts = []
    def fail(_, **kwargs):
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
    class Context(FakeContext):
        pages = []
        def on(self, *_):
            pass
        def close(self):
            raise RuntimeError("close failed")
    monkeypatch.setattr(wb, "sync_playwright", playwright)
    monkeypatch.setattr(wb, "_launch_context", lambda _, **kwargs: Context())
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
