from app.customer_reach_desktop import WinAppDesktop
from app.customer_reach_desktop import DesktopExecutionError
import pytest


@pytest.mark.parametrize("history,blocked", [
    ("卖家：你这边联系一下收件人拒收", False),
    ("卖家：拒收包裹后退回仓库", False),
    ("买家：拒收", True),
    ("买家：拒收广告", True),
    ("买家：收件人拒收广告", True),
    ("收件人拒收。买家：不要再发广告", True),
])
def test_logistics_refusal_does_not_mask_message_refusal(history, blocked):
    if blocked:
        with pytest.raises(DesktopExecutionError, match="拒收"):
            WinAppDesktop._check_refusal(history)
    else:
        WinAppDesktop._check_refusal(history)


def test_customer_document_uses_shallow_inspect_and_roots_subsequent_queries(monkeypatch):
    adapter = WinAppDesktop()
    calls = []
    def run(*args, **kwargs):
        calls.append(args)
        return {"selector": "customer-doc", "type": "Document", "name": "客户管理"} if args[0] == "inspect" else {"matches": []}
    monkeypatch.setattr(adapter, "_run", run)
    assert adapter._one(1, "客户管理", "Document")["selector"] == "customer-doc"
    adapter._search(1, "上一页", "ListItem")
    assert calls[0] == ("inspect", "-w", "1", "-d", "4", "--json")
    assert calls[1][calls[1].index("--root") + 1] == "customer-doc"
    adapter._search(2, "千牛消息聊天", "Document")
    assert "--root" not in calls[2]


def test_document_scope_is_cleared_after_business_tab_change(monkeypatch):
    adapter = WinAppDesktop()
    adapter.customer_root = (1, "old-doc")
    monkeypatch.setattr(adapter, "_run", lambda *args, **kwargs: {})
    assert adapter._search(1, "客户管理", "Document") == []
    assert adapter.customer_root is None


def test_offscreen_contact_scrolls_only_the_same_locked_row(monkeypatch):
    adapter = WinAppDesktop()
    row = {"selector": "locked-row", "type": "DataItem", "name": "L6 target active", "width": 200, "height": 100, "y": 100}
    monkeypatch.setattr(adapter, "_customer_page", lambda hwnd: ([row], {"selector": "actions"}))
    monkeypatch.setattr(adapter, "_row_identity", lambda *a: {"nickname": "target", "customer_key": "target"})
    monkeypatch.setattr(adapter, "_one", lambda *a: {"selector": "customer-doc"})
    scrolled = []
    def run(*args, **kwargs):
        if args[0] in {"scroll-into-view", "scroll"}:
            scrolled.append(args[1])
            return {}
        if args[1] == "actions":
            return {"selector": "action-row", "type": "DataItem", "name": "operation"}
        return {"selector": "contact", "type": "Button", "name": "旺旺洽谈", "height": 20 if scrolled else 0, "y": 130 if scrolled else 0}
    monkeypatch.setattr(adapter, "_run", run)
    result = adapter._first_customer(1, "已成单客户")
    assert scrolled == ["locked-row", "customer-doc"]
    assert result["nickname"] == "target"
    assert result["_contact"]["selector"] == "contact"


def test_query_retry_timing_does_not_double_count_retry_duration(monkeypatch):
    import subprocess
    from types import SimpleNamespace
    adapter = WinAppDesktop()
    ticks = iter([0, 20, 20, 30])
    monkeypatch.setattr("app.customer_reach_desktop.time.monotonic", lambda: next(ticks))
    results = iter([subprocess.TimeoutExpired("search", 20), SimpleNamespace(returncode=0, stdout="{}")])
    def run(*args, **kwargs):
        result = next(results)
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr("app.customer_reach_desktop.subprocess.run", run)
    adapter._run("search", "probe", json_output=True)
    assert [item["seconds"] for item in adapter.command_timings] == [20, 10]
