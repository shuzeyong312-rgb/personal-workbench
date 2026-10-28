"""Local maintenance of the collector's persistent browser."""
import asyncio
import os
from pathlib import Path
from threading import Event, Lock, Thread

from fastapi import APIRouter, HTTPException, Request

from app.collection.collector_1688 import _launch_context, _project_root, sync_playwright
from app.collection.service import COLLECTION_LOCK, BATCH_RUNTIME, acquire_collection_slot

router = APIRouter(prefix="/api/work-browser")


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

    def open(self):
        with self.lock:
            if self.state in ("opening", "managing", "closing"):
                return
            if self.state == "unknown":
                raise HTTPException(409, detail={"message": "浏览器状态未知，请关闭工作浏览器并重启后台。"})
            self.state, self.message = "opening", ""
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
                self.state = "idle" if closed else "unknown"
                self.message = "工作浏览器无法打开或已异常退出；请关闭相关窗口并重启后台后重试。"
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


@router.post("")
async def open_browser(request: Request):
    origin = os.getenv("PERSONAL_WORKBENCH_FRONTEND_ORIGIN", "")
    host = request.headers.get("host", "")
    if (not origin or request.headers.get("origin") != origin
            or host not in ("127.0.0.1:8200", origin.removeprefix("http://"))
            or request.headers.get("content-type") != "application/json"
            or request.headers.get("x-workbench-request") != "work-browser"
            or await request.body() != b"{}"):
        raise HTTPException(403, detail={"message": "请求来源无效"})
    WORK_BROWSER.open()
    return WORK_BROWSER.snapshot()
