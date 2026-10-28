"""Local maintenance of the collector's persistent browser."""
import asyncio
import os
from pathlib import Path
from threading import Event, Lock, Thread
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request

from app.collection.collector_1688 import _launch_context, _project_root, sync_playwright
from app.collection.service import COLLECTION_LOCK, BATCH_RUNTIME, acquire_collection_slot

router = APIRouter(prefix="/api/work-browser")


def _activate_windows_page(page):
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    token = "Workbench-" + uuid4().hex
    original = page.evaluate("token => { const old = document.title; document.title = token; return old; }", token)
    try:
        matches = []
        @callback_type
        def find_window(hwnd, _):
            title, name = ctypes.create_unicode_buffer(512), ctypes.create_unicode_buffer(128)
            user32.GetWindowTextW(hwnd, title, len(title))
            user32.GetClassNameW(hwnd, name, len(name))
            if name.value == "Chrome_WidgetWin_1" and token in title.value:
                matches.append(hwnd)
            return True
        for _ in range(10):
            matches.clear()
            user32.EnumWindows(find_window, 0)
            if matches:
                break
            page.wait_for_timeout(50)
        if len(matches) != 1:
            raise RuntimeError("Unable to identify the work browser window")
        hwnd = matches[0]
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        foreground = user32.GetForegroundWindow()
        current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
        foreground_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
        attached = bool(foreground_thread and foreground_thread != current_thread and
                        user32.AttachThreadInput(current_thread, foreground_thread, True))
        try:
            if not user32.SetForegroundWindow(hwnd):
                # A foreground input event lets Windows honor the user's explicit activation.
                if user32.GetAsyncKeyState(0x12) & 0x8000:
                    raise RuntimeError("Windows did not activate the work browser")
                user32.keybd_event(0x12, 0, 0, 0)
                try:
                    if not user32.SetForegroundWindow(hwnd):
                        raise RuntimeError("Windows did not activate the work browser")
                finally:
                    user32.keybd_event(0x12, 0, 2, 0)
        finally:
            if attached:
                user32.AttachThreadInput(current_thread, foreground_thread, False)
    finally:
        page.evaluate("([token, old]) => { if (document.title === token) document.title = old; }", [token, original])


def show_work_browser_window(context, page):
    """Restore the owned Chrome window and keep it within the active work area."""
    area = None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class MonitorInfo(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                        ("work", wintypes.RECT), ("flags", wintypes.DWORD)]

        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.MonitorFromWindow.restype = wintypes.HANDLE
        user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
        info = MonitorInfo()
        info.size = ctypes.sizeof(info)
        monitor = user32.MonitorFromWindow(user32.GetForegroundWindow(), 1)
        if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            area = {"left": info.work.left, "top": info.work.top,
                    "width": info.work.right - info.work.left, "height": info.work.bottom - info.work.top}
    if not area:
        area = page.evaluate("() => ({left: screen.availLeft, top: screen.availTop, width: screen.availWidth, height: screen.availHeight})")
    cdp = context.new_cdp_session(page)
    try:
        window = cdp.send("Browser.getWindowForTarget")
        window_id, bounds = window["windowId"], window["bounds"]
        cdp.send("Browser.setWindowBounds", {"windowId": window_id, "bounds": {"windowState": "normal"}})
        left, top = bounds.get("left", 0), bounds.get("top", 0)
        width, height = bounds.get("width", 0), bounds.get("height", 0)
        if (width <= 0 or height <= 0 or left < area["left"] or top < area["top"]
                or left + width > area["left"] + area["width"]
                or top + height > area["top"] + area["height"]):
            width, height = min(1200, area["width"]), min(800, area["height"])
            cdp.send("Browser.setWindowBounds", {"windowId": window_id, "bounds": {
                "left": area["left"] + max(0, (area["width"] - width) // 2),
                "top": area["top"] + max(0, (area["height"] - height) // 2),
                "width": width, "height": height}})
        page.bring_to_front()
        if os.name == "nt":
            _activate_windows_page(page)
    finally:
        cdp.detach()


def acquire_backend_lease(profile: Path):
    path = profile.resolve().parent / (profile.name + ".backend.lock")
    handle = open(path, "a+b")
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RuntimeError("工作浏览器配置已由另一个后台占用") from None
    return handle


class WorkBrowser:
    def __init__(self):
        self.lock = Lock()
        self.state = "idle"
        self.message = ""
        self.stop = Event()
        self.thread = None
        self.show_requested = False
        self.extensions_requested = False

    def snapshot(self):
        with self.lock:
            state, message = self.state, self.message
        if state == "idle" and BATCH_RUNTIME.is_busy():
            state = "collecting"
        elif state == "idle":
            if not COLLECTION_LOCK.acquire(blocking=False):
                state = "collecting"
            else:
                COLLECTION_LOCK.release()
        return {"status": state, "message": message}

    def open(self, *, extensions=False):
        with self.lock:
            if self.state in ("opening", "managing"):
                self.show_requested = True
                self.extensions_requested |= extensions
                return
            if self.state == "closing":
                return
            if self.state == "unknown":
                raise HTTPException(409, detail={"message": "浏览器状态未知，请关闭工作浏览器并重启后台。"})
            self.state, self.message = "opening", ""
            self.show_requested = True
            self.extensions_requested = extensions
            self.stop.clear()
            self.thread = Thread(target=self._run, daemon=True)
            self.thread.start()

    def _run(self):
        acquired = False
        context = None
        closed = False
        try:
            acquired = acquire_collection_slot()
            if not acquired:
                with self.lock:
                    self.state, self.message = "idle", "采集正在进行，请结束后重试。"
                return
            with sync_playwright() as playwright:
                context = _launch_context(playwright)
                def on_close(_):
                    nonlocal closed
                    closed = True
                context.on("close", on_close)
                try:
                    with self.lock:
                        self.state = "managing"
                    while not closed and not self.stop.is_set():
                        pages = context.pages
                        if not pages:
                            break
                        with self.lock:
                            show, extensions = self.show_requested, self.extensions_requested
                            self.show_requested = self.extensions_requested = False
                        if show or extensions:
                            try:
                                page = pages[0]
                                if extensions:
                                    page = next((item for item in pages if item.url == "chrome://extensions/"), None)
                                    if page is None:
                                        page = context.new_page()
                                        page.goto("chrome://extensions/")
                                show_work_browser_window(context, page)
                                with self.lock:
                                    self.message = ""
                            except Exception:
                                with self.lock:
                                    self.message = "无法显示工作浏览器窗口，请手动切换到该窗口后重试。"
                        try:
                            pages[0].wait_for_timeout(250)
                        except Exception:
                            if not closed:
                                raise
                finally:
                    with self.lock:
                        self.state = "closing"
                    if not closed:
                        context.close()
                        closed = True
            with self.lock:
                self.state = "idle" if closed else "unknown"
        except Exception:
            with self.lock:
                self.state = "idle" if context is None or closed else "unknown"
                self.message = ("工作浏览器无法打开；请检查 Chrome 或关闭占用该配置的窗口后重试。"
                                if context is None else "工作浏览器已异常退出；请关闭相关窗口并重启后台后重试。")
        finally:
            if acquired:
                if self.state == "unknown":
                    self.stop.wait()
                COLLECTION_LOCK.release()

    async def shutdown(self):
        self.stop.set()
        thread = self.thread
        if thread and thread.is_alive():
            await asyncio.to_thread(thread.join, 10)
            if thread.is_alive():
                with self.lock:
                    self.state = "unknown"
                raise RuntimeError("工作浏览器未能安全关闭")


WORK_BROWSER = WorkBrowser()


@router.get("")
def browser_status():
    return WORK_BROWSER.snapshot()


async def _open_browser(request: Request, *, extensions: bool):
    origin = os.getenv("PERSONAL_WORKBENCH_FRONTEND_ORIGIN", "")
    host = request.headers.get("host", "")
    if (not origin or request.headers.get("origin") != origin
            or host not in ("127.0.0.1:8200", origin.removeprefix("http://"))
            or request.headers.get("content-type") != "application/json"
            or request.headers.get("x-workbench-request") != "work-browser"
            or await request.body() != b"{}"):
        raise HTTPException(403, detail={"message": "请求来源无效"})
    if extensions:
        WORK_BROWSER.open(extensions=True)
    else:
        WORK_BROWSER.open()
    return WORK_BROWSER.snapshot()


@router.post("")
async def open_browser(request: Request):
    return await _open_browser(request, extensions=False)


@router.post("/extensions")
async def open_extensions(request: Request):
    return await _open_browser(request, extensions=True)
