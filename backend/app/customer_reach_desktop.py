"""Windows UIA workflow for one 1688 customer; selectors are always live queries."""
import json
import os
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import subprocess
import tempfile
import time


class DesktopExecutionError(RuntimeError):
    def __init__(self, message: str, *, may_have_sent: bool = False, send_failed: bool = False):
        super().__init__(message)
        self.may_have_sent = may_have_sent
        self.send_failed = send_failed


def _nodes(value):
    if isinstance(value, dict):
        if value.get("selector"):
            yield value
        for child in value.values():
            yield from _nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _nodes(child)


def _norm(value: str) -> str:
    return " ".join(value.split())


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _children_text(node) -> str:
    return " ".join(str(item.get("name", item.get("Name", ""))) for item in _walk(node))


def _clipboard_text(value=None):
    """Use Unicode clipboard text without a shell or an extra desktop dependency."""
    import ctypes
    from ctypes import wintypes

    user, kernel = ctypes.windll.user32, ctypes.windll.kernel32
    user.GetClipboardData.restype = wintypes.HANDLE
    user.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user.SetClipboardData.restype = wintypes.HANDLE
    kernel.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel.GlobalAlloc.restype = wintypes.HANDLE
    kernel.GlobalLock.argtypes = [wintypes.HANDLE]
    kernel.GlobalLock.restype = ctypes.c_void_p
    kernel.GlobalUnlock.argtypes = [wintypes.HANDLE]
    kernel.GlobalFree.argtypes = [wintypes.HANDLE]
    if not user.OpenClipboard(None):
        raise DesktopExecutionError("无法打开剪贴板，未输入文字")
    try:
        if value is None:
            handle = user.GetClipboardData(13)
            if not handle:
                return ""
            pointer = kernel.GlobalLock(handle)
            if not pointer:
                raise DesktopExecutionError("无法读取剪贴板")
            try:
                return ctypes.wstring_at(pointer)
            finally:
                kernel.GlobalUnlock(handle)
        data = (value + "\0").encode("utf-16-le")
        handle = kernel.GlobalAlloc(0x0002, len(data))
        if not handle:
            raise DesktopExecutionError("剪贴板内存分配失败")
        pointer = kernel.GlobalLock(handle)
        if not pointer:
            kernel.GlobalFree(handle)
            raise DesktopExecutionError("剪贴板内存不可写")
        ctypes.memmove(pointer, data, len(data))
        kernel.GlobalUnlock(handle)
        if not user.EmptyClipboard() or not user.SetClipboardData(13, handle):
            kernel.GlobalFree(handle)
            raise DesktopExecutionError("剪贴板写入失败")
    finally:
        user.CloseClipboard()


class WinAppDesktop:
    def __init__(self, command: str = "winapp"):
        self.command = command
        self.checkpoint = None

    def _run(self, *args: str, json_output: bool = False, allow_no_matches: bool = False, timeout_seconds: int = 20):
        if self.checkpoint:
            self.checkpoint()
        try:
            result = subprocess.run([self.command, "ui", *args], capture_output=True, text=True, timeout=timeout_seconds, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DesktopExecutionError("WinApp UIA CLI 无法启动或响应；未判定客户端登录状态，也未操作客户") from exc
        if result.returncode:
            if allow_no_matches and json_output and not result.stderr:
                try:
                    empty = json.loads(result.stdout)
                except json.JSONDecodeError:
                    empty = None
                if isinstance(empty, dict) and empty.get("matchCount") == 0 and empty.get("matches") == []:
                    return empty
            try:
                error = json.loads(result.stderr or result.stdout).get("error", {})
                code = error.get("code", "uia_error")
            except (json.JSONDecodeError, AttributeError):
                code = "uia_error"
            if not isinstance(code, str) or not code.replace("_", "").isalnum():
                code = "uia_error"
            raise DesktopExecutionError(f"Windows UI Automation {args[0]} 失败（{code}）；已停止当前操作")
        if json_output:
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                raise DesktopExecutionError("Windows UI Automation 返回格式无效") from exc
        return result.stdout

    def _windows(self, *, workbench: bool = False):
        windows = self._run("list-windows", "--json", json_output=True)
        candidates = [window for window in windows
                      if window.get("processName", "").casefold() == "aliworkbench"]
        if workbench:
            candidates = [window for window in candidates if "商家工作台" in window.get("title", "")]
        foreground = [window for window in candidates if window.get("isForeground")]
        matches = foreground if len(foreground) == 1 else [
            window for window in candidates if "商家工作台" in window.get("title", "")]
        if not matches:
            matches = [window for window in candidates if "接待中心" in window.get("title", "")]
        if not matches and len(candidates) == 1:
            # The client keeps a single top-level window while switching between workbench and reception UI.
            matches = candidates
        if len(matches) != 1:
            if not candidates:
                raise DesktopExecutionError("未找到可控的 1688 窗口；无法判断客户端是否登录，请确认工作台进程和交互桌面状态")
            raise DesktopExecutionError("1688 工作台窗口不唯一或不可用；已停止，未判定为未登录")
        try:
            import ctypes
            handle = int(matches[0]["hwnd"])
            if ctypes.windll.user32.IsIconic(handle):
                if self.checkpoint:
                    self.checkpoint()
                ctypes.windll.user32.ShowWindow(handle, 9)
        except (AttributeError, OSError, ValueError, TypeError):
            pass
        return matches[0]

    def _chat_window(self):
        windows = self._run("list-windows", "--json", json_output=True)
        matches = [window for window in windows if window.get("processName", "").casefold() == "aliworkbench"
                   and "接待中心" in window.get("title", "")]
        if len(matches) > 1:
            workbenches = [window for window in windows if window.get("processName", "").casefold() == "aliworkbench"
                           and window.get("title", "").endswith("-1688商家工作台")]
            if len(workbenches) == 1:
                title = workbenches[0]["title"].removesuffix("-1688商家工作台") + "-接待中心"
                matches = [window for window in matches if window.get("title") == title]
        if len(matches) != 1:
            raise DesktopExecutionError("未能唯一识别接待中心窗口")
        return matches[0]

    def _search(self, hwnd: int, text: str, control_type: str | None = None):
        args = ["search", text, "-w", str(hwnd), "--json"]
        if control_type:
            args.extend(["--type", control_type])
        result = self._run(*args, json_output=True, allow_no_matches=True)
        return list(_nodes(result))

    def _one(self, hwnd: int, text: str, control_type: str | None = None):
        matches = [node for node in self._search(hwnd, text, control_type)
                   if node.get("name", node.get("Name")) == text
                   and (control_type is None or node.get("type", node.get("controlType")) == control_type)]
        if len(matches) != 1:
            raise DesktopExecutionError(f"界面状态不确定：无法唯一识别“{text}”")
        return matches[0]

    def _invoke(self, hwnd: int, text: str):
        node = self._one(hwnd, text)
        self._run("invoke", node["selector"], "-w", str(hwnd), "--action", "invoke", "--json")

    def _capture(self, hwnd: int) -> bytes:
        data_dir = Path(__file__).parent.parent / "data"
        data_dir.mkdir(exist_ok=True)
        handle, path = tempfile.mkstemp(suffix=".png", dir=data_dir)
        os.close(handle)
        try:
            self._focus(hwnd)
            self._run("screenshot", "-w", str(hwnd), "--capture-screen", "--output", path, "--json")
            return Path(path).read_bytes()
        except OSError as exc:
            raise DesktopExecutionError("无法读取工作台运行时截图") from exc
        finally:
            Path(path).unlink(missing_ok=True)

    def _document(self, hwnd: int, nickname: str):
        matches = self._search(hwnd, nickname)
        documents = [node for node in matches if node.get("type", node.get("controlType")) == "Document"]
        labels = [node for node in matches if node.get("type", node.get("controlType")) == "Text"
                  and node.get("name", node.get("Name")) == nickname and not node.get("isOffscreen", False)]
        if len(documents) != 1:
            chats = [n for n in self._search(hwnd, "千牛消息聊天", "Document")
                     if n.get("type") == "Document" and n.get("name") == "千牛消息聊天"]
            panels = [n for n in self._search(hwnd, "1688商家版服务面板", "Document")
                      if n.get("type") == "Document" and n.get("name") == "1688商家版服务面板"]
            if len(chats) != 1 or len(panels) != 1:
                raise DesktopExecutionError("无法从当前会话唯一核对客户身份")
            identity = urlsplit(panels[0].get("value", ""))
            if identity.scheme != "https" or identity.hostname != "air.1688.com" or parse_qs(identity.query).get("chatLoginId") != [nickname]:
                raise DesktopExecutionError("服务面板的当前会话登录标识与客户不一致")
            documents = chats
        if not labels:
            raise DesktopExecutionError("当前聊天标题没有显示目标客户昵称")
        node = documents[0]
        result = self._run("get-value", node["selector"], "-w", str(hwnd), "--json", json_output=True)
        values = [value for item in _nodes(result) for key, value in item.items() if key in {"value", "text"} and isinstance(value, str)]
        if not values:
            values = [value for key, value in result.items() if key in {"value", "text"} and isinstance(value, str)] if isinstance(result, dict) else []
        document_text = values[0] if values else ""
        if nickname not in document_text:
            raise DesktopExecutionError("会话文档身份与目标客户不匹配")
        return node, document_text

    def _focus(self, hwnd: int):
        import ctypes
        if ctypes.windll.user32.IsIconic(hwnd):
            if self.checkpoint:
                self.checkpoint()
            ctypes.windll.user32.ShowWindow(hwnd, 9)
        tree = self._run("inspect", "-w", str(hwnd), "-d", "1", "--json", json_output=True)
        windows = tree.get("windows", []) if isinstance(tree, dict) else []
        elements = windows[0].get("elements", []) if windows else []
        root = next((node for node in _nodes(elements)), None)
        if root is None:
            raise DesktopExecutionError("无法读取目标窗口的当前 UIA 状态")
        try:
            self._run("focus", root["selector"], "-w", str(hwnd), "--json")
        except DesktopExecutionError as exc:
            # CEF window roots may reject keyboard focus after their window was raised.
            if "focus_not_acquired" not in str(exc) or ctypes.windll.user32.GetForegroundWindow() != hwnd:
                raise

    @staticmethod
    def _click_document_input(node, hwnd: int):
        # shortcut: layouts must keep the editor in the chat document's lower 6%; replace with a verified OCR anchor if that changes.
        import ctypes

        x = int(node.get("x", 0) + node.get("width", 0) * 0.5)
        y = int(node.get("y", 0) + node.get("height", 0) * 0.94)
        if node.get("width", 0) < 300 or node.get("height", 0) < 120 or x <= 0 or y <= 0:
            raise DesktopExecutionError("聊天输入区的实时窗口范围无效")
        user32 = ctypes.windll.user32
        if user32.GetForegroundWindow() != hwnd:
            # WinApp focus is the only allowed activation path; the caller re-checks afterward.
            raise DesktopExecutionError("接待中心未保持前台；请人工接管后重试")
        user32.SetCursorPos(x, y)
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        user32.mouse_event(0x0004, 0, 0, 0, 0)

    @staticmethod
    def _send_button_point(screenshot: bytes, node, labels) -> tuple[int, int]:
        from PIL import Image

        try:
            image = Image.open(BytesIO(screenshot)).convert("RGB")
        except Exception as exc:
            raise DesktopExecutionError("无法读取发送前截图") from exc
        left, top = int(node.get("x", 0)), int(node.get("y", 0))
        width, height = int(node.get("width", 0)), int(node.get("height", 0))
        if width < 300 or height < 120 or left < 0 or top < 0 or left + width > image.width or top + height > image.height:
            raise DesktopExecutionError("聊天窗口截图与实时 UIA 范围不一致")
        labels = [label for label in labels
                  if label.get("name", label.get("Name")) == "发送"
                  and label.get("type", label.get("controlType")) in {"Text", "Button"}
                  and label.get("isEnabled", True) is not False
                  and not label.get("isOffscreen", False)]
        if len(labels) != 1:
            raise DesktopExecutionError("UIA 未能唯一识别可见的发送按钮文字；已停止发送")
        label = labels[0]
        label_x = int(label.get("x", 0) + label.get("width", 0) / 2)
        label_y = int(label.get("y", 0) + label.get("height", 0) / 2)
        if not (left + width * 0.55 <= label_x <= left + width * 0.99
                and top + height * 0.78 <= label_y <= top + height * 0.99):
            raise DesktopExecutionError("发送文字不在聊天编辑区右下角的发送控件区域内")
        x0, x1 = left + int(width * 0.35), left + int(width * 0.99)
        y0, y1 = top + int(height * 0.78), top + int(height * 0.99)
        crop = image.crop((x0, y0, x1, y1))
        pixels = crop.load()
        min_width = max(40, int(width * 0.05))
        min_height = max(14, int(height * 0.012))
        groups = []
        for y in range(crop.height):
            runs = []
            run_start = None
            for x in range(crop.width + 1):
                blue = False
                if x < crop.width:
                    red, green, blue_value = pixels[x, y]
                    blue = blue_value >= 110 and blue_value > red * 1.3 and blue_value > green * 1.05
                if blue and run_start is None:
                    run_start = x
                elif not blue and run_start is not None:
                    if x - run_start >= min_width:
                        runs.append((run_start, y, x - 1, y))
                    run_start = None
            for run in runs:
                matching = [box for box in groups if run[1] <= box[3] + 2
                            and min(run[2], box[2]) - max(run[0], box[0]) >= min(run[2] - run[0], box[2] - box[0]) * 0.5]
                if matching:
                    box = matching[0]
                    box[0], box[2] = min(box[0], run[0]), max(box[2], run[2])
                    box[3] = run[3]
                    for extra in matching[1:]:
                        box[0], box[1] = min(box[0], extra[0]), min(box[1], extra[1])
                        box[2], box[3] = max(box[2], extra[2]), max(box[3], extra[3])
                        groups.remove(extra)
                else:
                    groups.append(list(run))
        candidates = []
        for x0c, y0c, x1c, y1c in groups:
            box_width, box_height = x1c - x0c + 1, y1c - y0c + 1
            if box_width < min_width or box_height < min_height or not 1.2 <= box_width / box_height <= 8:
                continue
            blue_count = sum(
                1 for red, green, blue_value in crop.crop((x0c, y0c, x1c + 1, y1c + 1)).getdata()
                if blue_value >= 110 and blue_value > red * 1.3 and blue_value > green * 1.05
            )
            if blue_count / (box_width * box_height) >= 0.45:
                candidates.append((x0 + x0c, y0 + y0c, x0 + x1c, y0 + y1c))
        if len(candidates) != 1:
            raise DesktopExecutionError("截图中无法唯一定位主发送按钮；已停止发送")
        x0c, y0c, x1c, y1c = candidates[0]
        if not (x0c <= label_x <= x1c and y0c <= label_y <= y1c):
            raise DesktopExecutionError("截图按钮区域与 UIA 发送文字位置不匹配；已停止发送")
        return (x0c + x1c) // 2, (y0c + y1c) // 2

    @staticmethod
    def _click_screen_point(point: tuple[int, int], hwnd: int):
        import ctypes

        user32 = ctypes.windll.user32
        if user32.GetForegroundWindow() != hwnd:
            raise DesktopExecutionError("接待中心未保持前台；请人工接管后重试", may_have_sent=False)
        if not user32.SetCursorPos(*point):
            raise DesktopExecutionError("无法将鼠标定位到已核验的发送按钮", may_have_sent=False)
        try:
            user32.mouse_event(0x0002, 0, 0, 0, 0)
            user32.mouse_event(0x0004, 0, 0, 0, 0)
        except Exception as exc:
            raise DesktopExecutionError("发送点击结果需人工核实", may_have_sent=True) from exc

    def prepare(self, task, update):
        window = self._windows()
        hwnd = int(window["hwnd"])
        self._focus(hwnd)
        update(step="打开客户管理")
        # Each action searches the current UIA tree again; slugs are never persisted.
        if not self._search(hwnd, "客户管理"):
            update(step="打开营销获客")
            self._invoke(hwnd, "营销获客")
        update(step="打开客户管理")
        self._invoke(hwnd, "客户管理")
        update(step="打开客户资产")
        self._run("click", self._one(hwnd, "客户资产")["selector"], "-w", str(hwnd), "--json")
        update(status="locating", step="按昵称精确搜索客户")
        edit = self._one(hwnd, "请输入买家昵称", "Edit")
        update(step="填写待搜索昵称")
        self._run("set-value", edit["selector"], task.customer_nickname, "-w", str(hwnd), "--json")
        search = [node for node in self._search(hwnd, "搜索") if node.get("type") == "Button"]
        if len(search) != 1:
            raise DesktopExecutionError("客户搜索按钮不唯一")
        update(step="搜索指定客户")
        self._run("invoke", search[0]["selector"], "-w", str(hwnd), "--action", "invoke", "--json")
        rows = [node for node in self._search(hwnd, task.customer_nickname) if node.get("type") == "DataItem"]
        if len(rows) != 1 or rows[0].get("name") != task.customer_nickname:
            raise DesktopExecutionError("买家昵称未唯一匹配；已停止操作")
        update(step="定位客户旺旺洽谈")
        contact = self._one(hwnd, "旺旺洽谈", "Button")
        self._run("scroll-into-view", contact["selector"], "-w", str(hwnd), "--json")
        contact = self._one(hwnd, "旺旺洽谈", "Button")
        rows = [node for node in self._search(hwnd, task.customer_nickname) if node.get("type") == "DataItem"]
        if len(rows) != 1:
            raise DesktopExecutionError("滚动后客户行发生变化；已停止操作")
        update(step="打开指定客户旺旺会话")
        self._run("invoke", contact["selector"], "-w", str(hwnd), "--action", "invoke", "--json")

        chat = self._chat_window()
        chat_hwnd = int(chat["hwnd"])
        update(status="preparing", step="核对旺旺会话身份")
        self._focus(chat_hwnd)
        doc, doc_text = self._document(chat_hwnd, task.customer_nickname)
        if task.message_text in doc_text or task.product_url in doc_text:
            raise DesktopExecutionError("会话中已有相同内容；为避免重复发送，任务已停止")
        update(step="确认聊天窗口与会话身份")
        screenshot = self._capture(chat_hwnd)
        update(screenshot=screenshot)
        doc, doc_text = self._document(chat_hwnd, task.customer_nickname)
        if task.message_text in doc_text or task.product_url in doc_text:
            raise DesktopExecutionError("会话内容变化；已停止草稿输入")
        update(step="向当前会话的可见编辑区填写草稿")
        self._click_document_input(doc, chat_hwnd)
        body = task.message_text + "\n" + task.product_url
        update(step="输入文案和商品链接")
        self._run("send-keys", body, "-w", str(chat_hwnd), "--via", "send-input", "--verbatim", "--json")
        screenshot = self._capture(chat_hwnd)
        update(screenshot=screenshot)
        doc, draft = self._document(chat_hwnd, task.customer_nickname)
        if _norm(draft).count(_norm(body)) != 1:
            raise DesktopExecutionError("可见草稿与预期内容不一致；禁止发送")
        screenshot = self._capture(chat_hwnd)
        update(status="awaiting_confirmation", step="客户身份和草稿已核对，等待本次发送确认",
               matched_customer=task.customer_nickname, draft_verified=True, screenshot=screenshot)

    def _inspect(self, hwnd: int):
        return self._run("inspect", "-w", str(hwnd), "-d", "12", "--json", json_output=True, timeout_seconds=60)

    @staticmethod
    def _row_nodes(tree):
        def walk(value):
            if isinstance(value, dict):
                if value.get("type", value.get("controlType")) == "DataItem":
                    yield value
                for child in value.values():
                    yield from walk(child)
            elif isinstance(value, list):
                for child in value:
                    yield from walk(child)
        return list(walk(tree))

    @staticmethod
    def _parse_customer_row(row, category):
        import re

        text = _children_text(row)
        nickname = str(row.get("name", row.get("Name", ""))).strip()
        name_match = re.search(r"(?:买家昵称|客户昵称|昵称)\s*[:：]\s*([^,，;；\s]+)", text)
        if name_match:
            nickname = name_match.group(1)
        login = re.search(r"(?:会员登录名|登录名|买家账号|客户账号|买家ID|客户ID)\s*[:：]\s*([\w@.-]+)", text, re.I)
        if not login:
            compact = re.fullmatch(r"L\d+\s+([^\s]+)\s+.+", nickname)
            if compact:
                nickname = compact.group(1)
                login = re.match(r"(.+)", nickname)
        key = f"login:{login.group(1)}" if login else ""
        denied = any(term in text for term in ("拒绝营销", "不同意营销", "已退订", "未授权营销"))
        explicit = next((term for term in ("营销授权：已授权", "已同意营销", "允许营销触达", "同意接收营销") if term in text), "")
        return {"customer_key": key, "nickname": nickname, "category": category,
                "eligible": bool(key and nickname and explicit and not denied),
                "authorization_evidence": explicit if explicit and not denied else None}

    def list_customers(self, category: str, update, *, first_only: bool = False, eligible_limit: int | None = None, test_scope: bool = False):
        """Read every page and include only rows with visible stable login and explicit marketing consent."""
        self.checkpoint = lambda: update()
        window = self._windows(workbench=True)
        hwnd = int(window["hwnd"])
        self._focus(hwnd)
        documents = [n for n in self._search(hwnd, "客户管理", "Document") if n.get("type") == "Document" and n.get("name") == "客户管理"]
        if not documents:
            update(step="打开客户管理")
            entry = self._one(hwnd, "客户管理", "Hyperlink")
            self._run("invoke", entry["selector"], "-w", str(hwnd), "--action", "invoke", "--json")
        update(step="恢复客户管理页面顶部")
        document = self._one(hwnd, "客户管理", "Document")
        self._run("scroll", document["selector"], "-w", str(hwnd), "--wheel", "30", "--json")
        update(step="打开全部客户明细")
        self._run("click", self._one(hwnd, "全部客户明细", "Text")["selector"], "-w", str(hwnd), "--json")
        update(step="打开客户资产")
        self._run("click", self._one(hwnd, "客户资产", "Text")["selector"], "-w", str(hwnd), "--json")
        label = "已成单客户" if category == "ordered" else "询盘客户"
        candidates = [node for node in self._search(hwnd, label, "TabItem")
                      if node.get("type") == "TabItem" and str(node.get("name", "")).startswith(label) and not node.get("isOffscreen", False)]
        if len(candidates) != 1:
            raise DesktopExecutionError(f"无法唯一识别“{label}”分类；已停止")
        update(step=f"筛选{label}")
        self._run("click", candidates[0]["selector"], "-w", str(hwnd), "--json")
        if first_only or test_scope:
            update(step="滚动显示第一页首位客户")
            document = self._one(hwnd, "客户管理", "Document")
            self._run("scroll", document["selector"], "-w", str(hwnd), "--wheel", "-4", "--json")
            if first_only:
                return [self._first_customer(hwnd, label)]
            customers = [self._first_customer(hwnd, label, index=index) for index in range(5)]
            if len({row['nickname'] for row in customers}) != 5:
                raise DesktopExecutionError("第一页前五位身份不唯一，未扩大范围")
            return customers
        customers, visited_pages = [], set()
        while True:
            tree = self._inspect(hwnd)
            rows = self._row_nodes(tree)
            if not rows:
                raise DesktopExecutionError("客户分类页面没有可读取的客户行；无法证明列表已加载，已停止")
            page = tuple(str(row.get("name", row.get("Name", ""))) for row in rows)
            if page in visited_pages:
                break
            visited_pages.add(page)
            parsed = [self._parse_customer_row(row, label) for row in rows]
            if test_scope:
                parsed = [dict(row, eligible=bool(row["customer_key"] and row["nickname"]),
                               authorization_evidence="用户明确授权本次前 5 位连续测试") for row in parsed]
            customers.extend(parsed)
            update(screenshot=self._capture(hwnd), step=f"已读取 {len(customers)} 条{label}列表记录")
            if eligible_limit is not None and sum(customer["eligible"] for customer in customers) >= eligible_limit:
                break
            if first_only:
                return customers[:1]
            next_buttons = [node for node in self._search(hwnd, "下一页", "Button")
                            if node.get("name", node.get("Name")) == "下一页" and not node.get("isOffscreen", False)]
            if len(next_buttons) != 1 or next_buttons[0].get("isEnabled") is False:
                break
            update(step=f"读取{label}列表下一页")
            self._run("invoke", next_buttons[0]["selector"], "-w", str(hwnd), "--action", "invoke", "--json")
        return customers

    def _first_customer(self, hwnd, label, *, index=0, scrolled=False):
        previous = self._one(hwnd, "上一页", "ListItem")
        if previous.get("isEnabled") is not False:
            raise DesktopExecutionError("无法证明当前为第一页；未选择客户")
        document = self._one(hwnd, "客户管理", "Document")
        tree = self._run("inspect", document["selector"], "-w", str(hwnd), "-d", "2", "--json", json_output=True)
        tables = [n for n in _nodes(tree) if n.get("type") == "Table" and n.get("height", 0) > 100]
        if len(tables) != 3:
            raise DesktopExecutionError("首位客户列表的主表、身份列和操作列结构无法核对")
        left = min(tables, key=lambda n: (n.get("x", 0), n.get("width", 0)))
        rows = self._run("inspect", left["selector"], "-w", str(hwnd), "-d", "3", "--json", json_output=True)
        items = [n for n in _nodes(rows) if n.get("type") == "DataItem" and n.get("name")]
        if not items:
            raise DesktopExecutionError("第一页首位客户没有可核对的身份文字")
        # Do not infer a login ID from a display nickname or table position.
        if len(items) <= index:
            raise DesktopExecutionError("第一页不足五位可识别客户，未翻页补充")
        row = items[index]
        if row.get("width", 0) <= 0 or row.get("height", 0) <= 0:
            if index and not scrolled:
                self._run("scroll-into-view", row["selector"], "-w", str(hwnd), "--json")
                return self._first_customer(hwnd, label, index=index, scrolled=True)
            raise DesktopExecutionError("第一页首行当前不可见；未选择屏幕外的其他客户")
        import re
        texts = [n.get("name", "") for n in _nodes(row) if n.get("type") == "Text"]
        if len(texts) != 3 or not re.fullmatch(r"L\d+", texts[0]) or _norm(row["name"]) != _norm(" ".join(texts)):
            raise DesktopExecutionError("第一页首行的等级、昵称和状态不能唯一分离")
        right = max(tables, key=lambda n: n.get("x", 0))
        actions = self._run("inspect", right["selector"], "-w", str(hwnd), "-d", "3", "--json", json_output=True)
        action_rows = [n for n in _nodes(actions) if n.get("type") == "DataItem" and n.get("name")]
        buttons = [n for n in _nodes(action_rows[index]) if n.get("type") == "Button" and n.get("name") == "旺旺洽谈"] if len(action_rows) > index else []
        if len(buttons) != 1 or buttons[0].get("height", 0) <= 0 or not (row["y"] <= buttons[0].get("y", 0) < row["y"] + row["height"]):
            raise DesktopExecutionError("第一页首行身份列与旺旺按钮无法按同行位置唯一绑定")
        # This is a display identity for a non-sending task, never a marketing login/consent claim.
        return {"customer_key": "preview:first:" + texts[1], "nickname": texts[1], "category": label,
                "eligible": False, "authorization_evidence": None, "_contact": buttons[0]}

    def _customer_contact(self, hwnd: int, recipient):
        key, nickname = recipient["customer_key"], recipient["nickname"]
        matches = []
        def find(value):
            if isinstance(value, dict):
                if value.get("type", value.get("controlType")) == "DataItem":
                    text = _children_text(value)
                    if key.split(":", 1)[-1] in text and nickname in text:
                        matches.extend(node for node in _walk(value)
                                       if node.get("name", node.get("Name")) == "旺旺洽谈"
                                       and node.get("type", node.get("controlType")) == "Button"
                                       and node.get("selector"))
                else:
                    for child in value.values():
                        find(child)
            elif isinstance(value, list):
                for child in value:
                    find(child)
        find(self._inspect(hwnd))
        if len(matches) != 1:
            raise DesktopExecutionError("客户行、稳定身份和旺旺洽谈按钮不能唯一对应；已停止")
        return matches[0]

    def prepare_customer(self, task, recipient, update):
        self.checkpoint = lambda: update()
        if task.execution_mode in {"desktop_preview", "desktop_single", "desktop_batch5"}:
            prepare_started = time.monotonic()
            hwnd = int(self._windows(workbench=True)["hwnd"])
            self._focus(hwnd)
            first = self._first_customer(hwnd, recipient["category"], index=recipient["sequence"] - 1) if task.execution_mode == "desktop_batch5" else self._first_customer(hwnd, recipient["category"])
            if first["customer_key"] != recipient["customer_key"] or first["nickname"] != recipient["nickname"]:
                raise DesktopExecutionError("第一页首位客户身份发生变化，未打开会话")
            update(timing={"locate_seconds": round(time.monotonic() - prepare_started, 3)}, step="打开已重新核对的第一页客户旺旺")
            started = time.monotonic()
            self._run("invoke", first["_contact"]["selector"], "-w", str(hwnd), "--action", "invoke", "--json")
            chat_hwnd = int(self._chat_window()["hwnd"])
            self._focus(chat_hwnd)
            self._document(chat_hwnd, recipient["nickname"])
            update(timing={"open_chat_seconds": round(time.monotonic() - started, 3)})
            started = time.monotonic()
            if task.execution_mode in {"desktop_single", "desktop_batch5"}:
                self._prepare_full_draft(task, recipient, chat_hwnd, update)
            else:
                self._preview_draft(task, recipient, chat_hwnd, update)
            update(timing={"input_verify_seconds": round(time.monotonic() - started, 3),
                           "front_occupied_prepare_seconds": round(time.monotonic() - prepare_started, 3)})
            return True
        prepare_started = time.monotonic()
        window = self._windows(workbench=True)
        hwnd = int(window["hwnd"])
        self._focus(hwnd)
        started = time.monotonic()
        contact = self._customer_contact(hwnd, recipient)
        update(timing={"locate_seconds": round(time.monotonic() - started, 3)})
        update(step=f"打开第 {recipient['sequence']} 位客户旺旺")
        started = time.monotonic()
        self._run("scroll-into-view", contact["selector"], "-w", str(hwnd), "--json")
        contact = self._customer_contact(hwnd, recipient)
        self._run("invoke", contact["selector"], "-w", str(hwnd), "--action", "invoke", "--json")
        chat = self._chat_window()
        chat_hwnd = int(chat["hwnd"])
        update(status="preparing", step="核对旺旺会话身份")
        self._focus(chat_hwnd)
        doc, text = self._document(chat_hwnd, task.customer_nickname)
        stable_login = recipient["customer_key"].split(":", 1)[-1]
        identity_nodes = [node for node in self._search(chat_hwnd, stable_login)
                          if node.get("name", node.get("Name")) == stable_login and not node.get("isOffscreen", False)]
        if len(identity_nodes) != 1 or task.customer_nickname not in text:
            raise DesktopExecutionError("聊天窗口未能同时核对客户昵称和稳定登录标识")
        update(timing={"open_chat_seconds": round(time.monotonic() - started, 3)})
        started = time.monotonic()
        self._prepare_full_draft(task, recipient, chat_hwnd, update)
        update(timing={"input_verify_seconds": round(time.monotonic() - started, 3),
                       "front_occupied_prepare_seconds": round(time.monotonic() - prepare_started, 3)})

    def _preview_editor_snapshot(self, hwnd, nickname):
        import shutil
        from PIL import Image, ImageOps

        doc, _ = self._document(hwnd, nickname)
        root = next(_nodes(self._run("inspect", "-w", str(hwnd), "-d", "1", "--json", json_output=True)), None)
        if not root or root.get("type") != "Window":
            raise DesktopExecutionError("无法核对接待中心当前窗口范围")
        # shortcut: Qt editor has a 76px toolbar gap and 56px footer; recalibrate after client layout changes.
        left, top = int(doc["x"] + 12), int(doc["y"] + doc["height"] + 76)
        right, bottom = int(doc["x"] + doc["width"] - 35), int(root["y"] + root["height"] - 56)
        if right - left < 300 or not 40 <= bottom - top <= 400:
            raise DesktopExecutionError("编辑区与聊天文档的当前布局不匹配，未输入草稿")
        screenshot = self._capture(hwnd)
        image = Image.open(BytesIO(screenshot)).convert("RGB")
        if image.size == (root["width"], root["height"]):
            box = (left - root["x"], top - root["y"], right - root["x"], bottom - root["y"])
        elif image.width >= root["x"] + root["width"] and image.height >= root["y"] + root["height"]:
            box = (left, top, right, bottom)
        else:
            raise DesktopExecutionError("截图范围与当前接待中心不一致")
        crop = image.crop(box).convert("L").point(lambda value: 0 if value < 150 else 255)
        crop = ImageOps.expand(crop.resize((crop.width * 3, crop.height * 3)), border=20, fill="white")
        payload = BytesIO()
        crop.save(payload, format="PNG")
        command = shutil.which("tesseract") or str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Tesseract-OCR" / "tesseract.exe")
        if self.checkpoint:
            self.checkpoint()
        try:
            result = subprocess.run([command, "stdin", "stdout", "--psm", "6", "-l", "eng"], input=payload.getvalue(), capture_output=True, timeout=15, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DesktopExecutionError("无法运行已安装的 Tesseract，未判定草稿内容") from exc
        if result.returncode:
            raise DesktopExecutionError("编辑区 OCR 失败，未判定草稿内容")
        return (int((left + right) / 2), int((top + bottom) / 2)), _norm(result.stdout.decode("utf-8").strip()).casefold(), screenshot

    def _preview_draft(self, task, recipient, hwnd, update):
        from hashlib import sha256

        def digest(text):
            return sha256(_norm(text).encode("utf-8")).hexdigest()

        def focus_editor(point):
            update(step="聚焦已核对会话的可见编辑区")
            self._click_screen_point(point, hwnd)
            self._run("send-keys", "ctrl+end", "-w", str(hwnd), "--via", "send-input", "--json")

        point, before, _ = self._preview_editor_snapshot(hwnd, recipient["nickname"])
        state = recipient.get("preview_state") or {}
        marker = task.message_text.casefold()
        if task.message_text != "X":
            raise DesktopExecutionError("非发送验收只允许固定单字符草稿探针")
        if state.get("restored") and digest(before) == state.get("baseline_hash"):
            update(status="awaiting_confirmation", step="恢复后客户和原草稿摘要已重新核对", draft_verified=True)
            return
        if state.get("cleanup_required") and marker not in before and digest(before) == state.get("baseline_hash"):
            state = {}
        if state.get("cleanup_required"):
            if before.count(marker) != 1 or digest(before.replace(marker, "", 1)) != state.get("baseline_hash"):
                raise DesktopExecutionError("遗留验收草稿与原始摘要不一致；未自动重写或删除")
        else:
            focus_editor(point)
            point, before, _ = self._preview_editor_snapshot(hwnd, recipient["nickname"])
            if marker in before:
                raise DesktopExecutionError("编辑区已有相同测试字符，未输入草稿")
            state = {"marker": task.message_text, "baseline_hash": digest(before), "cleanup_required": True}
            update(step="追加单字符非发送草稿", preview_state=state)
            self._run("send-keys", task.message_text, "-w", str(hwnd), "--via", "post-message", "--verbatim", "--json")
            point, visible, screenshot = self._preview_editor_snapshot(hwnd, recipient["nickname"])
            if visible.count(marker) != 1 or digest(visible.replace(marker, "", 1)) != state["baseline_hash"]:
                raise DesktopExecutionError("可见编辑区变化不止测试字符；未自动删除，需核对草稿")
            update(step="非发送测试草稿已预览，准备清理", screenshot=screenshot)
        focus_editor(point)
        _, visible, _ = self._preview_editor_snapshot(hwnd, recipient["nickname"])
        if not visible.endswith(marker) or visible.count(marker) != 1 or digest(visible.replace(marker, "", 1)) != state["baseline_hash"]:
            raise DesktopExecutionError("清理前编辑区已变化，未删除草稿")
        update(step="仅删除本次追加的单字符草稿")
        self._run("send-keys", "backspace", "-w", str(hwnd), "--via", "send-input", "--json")
        _, restored, _ = self._preview_editor_snapshot(hwnd, recipient["nickname"])
        if digest(restored) != state["baseline_hash"]:
            raise DesktopExecutionError("清理后编辑区与原始摘要不一致；未重复删除")
        update(status="awaiting_confirmation", step="非发送草稿已预览并清理，原始编辑区 OCR 摘要一致",
               matched_customer=recipient["nickname"], draft_verified=True,
               preview_state={**state, "cleanup_required": False, "restored": True})

    def send_customer(self, task, recipient, update):
        if task.execution_mode == "desktop_preview":
            raise DesktopExecutionError("非发送验收任务禁止发送")
        self._send_single(task, recipient, update)

    @staticmethod
    def _message_body(task):
        return task.message_text + "\n" + task.product_url

    @staticmethod
    def _check_refusal(history):
        if any(term in history for term in ("拒绝营销", "拒收", "退订", "不要再发", "别再发", "不要打扰", "不需要推广", "不要发广告")):
            raise DesktopExecutionError("当前客户记录含明确拒收表达，未发送")

    def _read_qt_editor(self, hwnd, nickname):
        from uuid import uuid4
        point, _, _ = self._preview_editor_snapshot(hwnd, nickname)
        self._click_screen_point(point, hwnd)
        previous = _clipboard_text()
        sentinel = str(uuid4())
        try:
            _clipboard_text(sentinel)
            self._run("send-keys", "ctrl+a", "-w", str(hwnd), "--via", "send-input", "--json")
            self._run("send-keys", "ctrl+c", "-w", str(hwnd), "--via", "send-input", "--json")
            copied = _clipboard_text()
            self._run("send-keys", "ctrl+end", "-w", str(hwnd), "--via", "send-input", "--json")
            if copied == sentinel:
                _, visible, _ = self._preview_editor_snapshot(hwnd, nickname)
                if visible:
                    raise DesktopExecutionError("可见编辑区与复制结果不一致")
                return ""
            return copied.replace("\r\n", "\n").replace("\r", "\n")
        finally:
            _clipboard_text(previous)

    def _prepare_full_draft(self, task, recipient, hwnd, update):
        _, history = self._document(hwnd, recipient["nickname"])
        self._check_refusal(history)
        update(preview_state={"verified_chat_login_id": recipient["customer_key"].split(":", 1)[-1],
                              "refusal_check": "no_explicit_refusal_in_loaded_records",
                              "authorization_scope": recipient.get("authorization_evidence")})
        body = self._message_body(task)
        if _norm(task.message_text) in _norm(history):
            raise DesktopExecutionError("聊天记录已有相同完整消息，未重复发送")
        current = self._read_qt_editor(hwnd, recipient["nickname"])
        if current and current != body:
            raise DesktopExecutionError("可见编辑区已有其他草稿，未覆盖")
        if not current:
            point, _, _ = self._preview_editor_snapshot(hwnd, recipient["nickname"])
            self._click_screen_point(point, hwnd)
            previous = _clipboard_text()
            try:
                _clipboard_text(body)
                update(step="向已核对的 Qt 可见编辑区粘贴完整文案和链接")
                self._run("send-keys", "ctrl+v", "-w", str(hwnd), "--via", "send-input", "--json")
            finally:
                _clipboard_text(previous)
        if self._read_qt_editor(hwnd, recipient["nickname"]) != body:
            raise DesktopExecutionError("Qt 可见编辑区完整回读与预期不一致，未发送")
        self._run("send-keys", "ctrl+home", "-w", str(hwnd), "--via", "send-input", "--json")
        update(screenshot=self._capture(hwnd), step="完整草稿已逐字回读，核对开头")
        self._run("send-keys", "ctrl+end", "-w", str(hwnd), "--via", "send-input", "--json")
        update(status="awaiting_confirmation", step="完整中文、Emoji、换行和链接已回读一致，未发送",
               screenshot=self._capture(hwnd), matched_customer=recipient["nickname"], draft_verified=True)

    def _send_single(self, task, recipient, update):
        if recipient.get("send_attempts", 0):
            raise DesktopExecutionError("本次发送动作已经占用，禁止再次点击", may_have_sent=True)
        self.checkpoint = lambda: update()
        started = time.monotonic()
        hwnd = int(self._chat_window()["hwnd"])
        self._focus(hwnd)
        _, history = self._document(hwnd, recipient["nickname"])
        self._check_refusal(history)
        body = self._message_body(task)
        if _norm(task.message_text) in _norm(history):
            raise DesktopExecutionError("当前聊天记录已有完整相同消息，未重复发送")
        if self._read_qt_editor(hwnd, recipient["nickname"]) != body:
            raise DesktopExecutionError("发送前 Qt 可见草稿不一致，未发送")
        root = next(_nodes(self._run("inspect", "-w", str(hwnd), "-d", "1", "--json", json_output=True)))
        labels = self._search(hwnd, "发送")
        screenshot = self._capture(hwnd)
        from PIL import Image
        size = Image.open(BytesIO(screenshot)).size
        relative = size == (root["width"], root["height"])
        bounds = dict(root)
        if relative:
            bounds.update(x=0, y=0)
            labels = [dict(n, x=n.get("x", 0) - root["x"], y=n.get("y", 0) - root["y"]) for n in labels]
        visible_labels = [n for n in labels if n.get("name") == "发送" and n.get("type") in {"Text", "Button"} and not n.get("isOffscreen", False)]
        if visible_labels:
            point = self._send_button_point(screenshot, bounds, labels)
        else:
            doc, _ = self._document(hwnd, recipient["nickname"])
            offset_x, offset_y = (root["x"], root["y"]) if relative else (0, 0)
            point = self._ocr_send_button(screenshot, bounds, dict(doc, x=doc["x"]-offset_x, y=doc["y"]-offset_y))
        if relative:
            point = (point[0] + root["x"], point[1] + root["y"])
        _, history = self._document(hwnd, recipient["nickname"])
        self._check_refusal(history)
        if _norm(task.message_text) in _norm(history):
            raise DesktopExecutionError("点击前已有相同消息，未发送")
        update(claim_send=True, timing={"send_preparation_seconds": round(time.monotonic() - started, 3)},
               step="发送动作已持久化占用，仅执行一次点击", screenshot=screenshot)
        try:
            self._click_screen_point(point, hwnd)
            update(step="已执行一次发送点击，仅核验结果，不重发")
            echo_started = time.monotonic()
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                _, history = self._document(hwnd, recipient["nickname"])
                matches = _norm(history).count(_norm(body))
                if any(term in history for term in ("发送失败", "重试发送", "消息发送失败")):
                    raise DesktopExecutionError("点击后出现发送失败提示；禁止重发", may_have_sent=True)
                if self._single_echo_matches(history, task):
                    update(timing={"echo_verify_seconds": round(time.monotonic() - echo_started, 3),
                                   "front_occupied_send_seconds": round(time.monotonic() - started, 3)},
                           screenshot=self._capture(hwnd), step="唯一完整消息、原链接和 Offer ID 回显已核对")
                    return
                if matches > 1:
                    raise DesktopExecutionError("存在多个完整消息回显，禁止重发", may_have_sent=True)
                time.sleep(0.5)
            raise DesktopExecutionError("一次点击后回显尚无法确认，禁止重发", may_have_sent=True)
        except Exception as exc:
            if isinstance(exc, DesktopExecutionError):
                exc.may_have_sent = True
                raise
            raise DesktopExecutionError("一次点击后核验异常，禁止重发", may_have_sent=True) from exc

    @staticmethod
    def _single_echo_matches(history, task):
        import re

        source, message = _norm(history), _norm(task.message_text)
        if source.count(message) != 1 or source.count(task.product_url) != 1 or re.findall(r"https?://[^\s]+", source).count(task.product_url) != 1:
            return False
        start = source.index(message) + len(message)
        end = source.find(task.product_url, start)
        if end < start or end-start > 500:
            return False
        # A rendered product card inserts metadata before its URL; a new message boundary must not.
        gap = source[start:end]
        if any(term in gap for term in ("未读", "已读", "发送失败", "重试")) or re.search(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}", gap):
            return False
        return not any(term in source for term in ("发送失败", "重试发送", "消息发送失败"))

    def verify_single_result(self, task, recipient, update):
        """Observation only: never focus, type, claim, or click when reconciling an unknown send."""
        hwnd = int(self._chat_window()["hwnd"])
        _, history = self._document(hwnd, recipient["nickname"])
        if not self._single_echo_matches(history, task):
            raise DesktopExecutionError("只读复核未通过，保持 unknown，不重发", may_have_sent=True)
        update(screenshot=self._capture(hwnd), step="只读复核：唯一正文与同一消息商品卡片原链接一致")

    def _ocr_send_button(self, screenshot, root, doc):
        import shutil
        from PIL import Image, ImageOps

        image = Image.open(BytesIO(screenshot)).convert("RGB")
        left = max(0, int(doc["x"] + doc["width"] * .75))
        right = min(image.width, int(doc["x"] + doc["width"]))
        top = max(0, int(root.get("y", 0) + root["height"] * .90))
        bottom = min(image.height, int(root.get("y", 0) + root["height"] * .99))
        points = []
        for y in range(top, bottom):
            for x in range(left, right):
                red, green, blue = image.getpixel((x, y))
                if blue >= 110 and blue > red * 1.3 and blue > green * 1.05:
                    points.append((x, y))
        if not points:
            raise DesktopExecutionError("实时编辑区右下方没有可核验的启用发送按钮")
        x0, y0 = min(x for x, y in points), min(y for x, y in points)
        x1, y1 = max(x for x, y in points) + 1, max(y for x, y in points) + 1
        width, height = x1-x0, y1-y0
        if not 40 <= width <= 150 or not 14 <= height <= 60 or len(points)/(width*height) < .60:
            raise DesktopExecutionError("发送按钮蓝色区域不唯一或布局已变化")
        crop = image.crop((x0+int(width*.12), y0+int(height*.125), x0+int(width*.65), y0+int(height*.875)))
        crop = ImageOps.expand(ImageOps.invert(crop.convert("L")).resize((crop.width*4, crop.height*4)), border=20, fill=255)
        payload = BytesIO()
        crop.save(payload, format="PNG")
        command = shutil.which("tesseract") or str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Tesseract-OCR" / "tesseract.exe")
        args = [command, "stdin", "stdout", "-l", "chi_sim", "--psm", "7"]
        if os.getenv("TESSDATA_PREFIX"):
            args.extend(["--tessdata-dir", os.environ["TESSDATA_PREFIX"]])
        result = subprocess.run(args, input=payload.getvalue(), capture_output=True, timeout=15, check=False)
        recognized = result.stdout.decode("utf-8").strip().replace(" ", "").strip("|丨")
        if result.returncode or recognized != "发送":
            raise DesktopExecutionError("实时蓝色按钮的中文 OCR 不是唯一“发送”，未点击")
        # Click the text half of the verified button, keeping clear of its dropdown arrow.
        return x0+int(width*.40), y0+height//2

    def send(self, task, update):
        if getattr(task, "execution_mode", None) == "desktop_preview":
            raise DesktopExecutionError("非发送验收任务禁止发送")
        try:
            chat = self._chat_window()
            hwnd = int(chat["hwnd"])
            self._focus(hwnd)
            doc, draft = self._document(hwnd, task.customer_nickname)
            body = task.message_text + "\n" + task.product_url
            if _norm(draft).count(_norm(body)) != 1:
                raise DesktopExecutionError("发送前客户或草稿状态已变化", may_have_sent=False)
            screenshot = self._capture(hwnd)
            update(screenshot=screenshot)
            doc, draft = self._document(hwnd, task.customer_nickname)
            if _norm(draft).count(_norm(body)) != 1:
                raise DesktopExecutionError("截图后客户或草稿状态变化", may_have_sent=False)
            send_labels = self._search(hwnd, "发送")
            button_point = self._send_button_point(screenshot, doc, send_labels)
            _, draft = self._document(hwnd, task.customer_nickname)
            if _norm(draft).count(_norm(body)) != 1:
                raise DesktopExecutionError("发送按钮定位后客户或草稿状态变化", may_have_sent=False)
        except DesktopExecutionError:
            raise
        except Exception as exc:
            raise DesktopExecutionError("发送前桌面校验异常；未触发发送", may_have_sent=False) from exc

        self._click_screen_point(button_point, hwnd)
        try:
            update(step="等待聊天记录回显")
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                _, history = self._document(hwnd, task.customer_nickname)
                failure = any(term in history for term in ("发送失败", "发送失败，请重试", "重试发送"))
                if failure:
                    raise DesktopExecutionError("工作台明确显示发送失败", send_failed=True)
                if _norm(history).count(_norm(body)) == 1:
                    update(screenshot=self._capture(hwnd))
                    return
                time.sleep(0.25)
            raise DesktopExecutionError("未能唯一核验聊天记录回显；禁止重发", may_have_sent=True)
        except DesktopExecutionError:
            raise
        except Exception as exc:
            raise DesktopExecutionError("发送后遇到未预期错误，请人工核对消息记录", may_have_sent=True) from exc
