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


class WinAppDesktop:
    def __init__(self, command: str = "winapp"):
        self.command = command
        self.checkpoint = None

    def _run(self, *args: str, json_output: bool = False, allow_no_matches: bool = False):
        if self.checkpoint:
            self.checkpoint()
        try:
            result = subprocess.run([self.command, "ui", *args], capture_output=True, text=True, timeout=20, check=False)
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
        return self._run("inspect", "-w", str(hwnd), "-d", "12", "--json", json_output=True)

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
        key = f"login:{login.group(1)}" if login else ""
        denied = any(term in text for term in ("拒绝营销", "不同意营销", "已退订", "未授权营销"))
        explicit = next((term for term in ("营销授权：已授权", "已同意营销", "允许营销触达", "同意接收营销") if term in text), "")
        return {"customer_key": key, "nickname": nickname, "category": category,
                "eligible": bool(key and nickname and explicit and not denied),
                "authorization_evidence": explicit if explicit and not denied else None}

    def list_customers(self, category: str, update, *, first_only: bool = False):
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
        if first_only:
            update(step="滚动显示第一页首位客户")
            document = self._one(hwnd, "客户管理", "Document")
            self._run("scroll", document["selector"], "-w", str(hwnd), "--wheel", "-4", "--json")
            return [self._first_customer(hwnd, label)]
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
            customers.extend(self._parse_customer_row(row, label) for row in rows)
            update(screenshot=self._capture(hwnd), step=f"已读取 {len(customers)} 条{label}列表记录")
            if first_only:
                return customers[:1]
            next_buttons = [node for node in self._search(hwnd, "下一页", "Button")
                            if node.get("name", node.get("Name")) == "下一页" and not node.get("isOffscreen", False)]
            if len(next_buttons) != 1 or next_buttons[0].get("isEnabled") is False:
                break
            update(step=f"读取{label}列表下一页")
            self._run("invoke", next_buttons[0]["selector"], "-w", str(hwnd), "--action", "invoke", "--json")
        return customers

    def _first_customer(self, hwnd, label):
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
        row = items[0]
        if row.get("width", 0) <= 0 or row.get("height", 0) <= 0:
            raise DesktopExecutionError("第一页首行当前不可见；未选择屏幕外的其他客户")
        import re
        texts = [n.get("name", "") for n in _nodes(row) if n.get("type") == "Text"]
        if len(texts) != 3 or not re.fullmatch(r"L\d+", texts[0]) or _norm(row["name"]) != _norm(" ".join(texts)):
            raise DesktopExecutionError("第一页首行的等级、昵称和状态不能唯一分离")
        right = max(tables, key=lambda n: n.get("x", 0))
        actions = self._run("inspect", right["selector"], "-w", str(hwnd), "-d", "3", "--json", json_output=True)
        action_rows = [n for n in _nodes(actions) if n.get("type") == "DataItem" and n.get("name")]
        buttons = [n for n in _nodes(action_rows[0]) if n.get("type") == "Button" and n.get("name") == "旺旺洽谈"] if action_rows else []
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
        if task.execution_mode == "desktop_preview":
            hwnd = int(self._windows(workbench=True)["hwnd"])
            self._focus(hwnd)
            first = self._first_customer(hwnd, recipient["category"])
            if first["customer_key"] != recipient["customer_key"] or first["nickname"] != recipient["nickname"]:
                raise DesktopExecutionError("第一页首位客户身份发生变化，未打开会话")
            update(step="打开已重新核对的第一页首位客户旺旺")
            self._run("invoke", first["_contact"]["selector"], "-w", str(hwnd), "--action", "invoke", "--json")
            chat_hwnd = int(self._chat_window()["hwnd"])
            self._focus(chat_hwnd)
            self._document(chat_hwnd, recipient["nickname"])
            self._preview_draft(task, recipient, chat_hwnd, update)
            return True
        window = self._windows()
        hwnd = int(window["hwnd"])
        self._focus(hwnd)
        contact = self._customer_contact(hwnd, recipient)
        update(step=f"打开第 {recipient['sequence']} 位客户旺旺")
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
        body = task.message_text + "\n" + task.product_url
        if task.message_text in text or task.product_url in text:
            raise DesktopExecutionError("会话记录中已有相同内容；为避免重复发送，已停止")
        update(screenshot=self._capture(chat_hwnd), step="向当前会话可见编辑区填写草稿")
        self._click_document_input(doc, chat_hwnd)
        self._run("send-keys", body, "-w", str(chat_hwnd), "--via", "send-input", "--verbatim", "--json")
        screenshot = self._capture(chat_hwnd)
        update(screenshot=screenshot)
        _, draft = self._document(chat_hwnd, task.customer_nickname)
        if _norm(draft).count(_norm(body)) != 1:
            raise DesktopExecutionError("可见草稿与预期不一致；禁止发送")
        update(screenshot=self._capture(chat_hwnd), status="awaiting_confirmation",
               step="客户身份和可见草稿已核验，等待本客户确认", matched_customer=task.customer_nickname, draft_verified=True)

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
        self.send(task, update)

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
