from types import SimpleNamespace

import pytest

from app.customer_reach_desktop import DesktopExecutionError, WinAppDesktop


@pytest.fixture
def batch(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app import database, customer_reach as reach
    from app.models import Base, CustomerReachCampaign
    from datetime import datetime, timezone

    engine = create_engine(f"sqlite:///{tmp_path / 'batch.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    monkeypatch.setattr(database, "engine", engine)
    queue, sends = [], []
    monkeypatch.setattr(reach._runner, "submit", lambda fn, *args: queue.append((fn, args)))
    rows = [{"customer_key": f"login:buyer-{i}", "nickname": f"buyer-{i}", "category": "已成单客户", "shop_title": "shop"} for i in range(5)]
    monkeypatch.setattr(WinAppDesktop, "list_customers", lambda *a, **kw: rows)
    monkeypatch.setattr(WinAppDesktop, "prepare_customer", lambda *a: True)

    def send(self, task, recipient, update):
        assert recipient["nickname"] not in sends
        update(claim_send=True)
        sends.append(recipient["nickname"])

    monkeypatch.setattr(WinAppDesktop, "send_customer", send)
    with Session(engine) as db:
        db.add(CustomerReachCampaign(id="batch", customer_category="ordered", message_text="body", product_url="https://detail.1688.com/offer/1.html",
                                    content_fingerprint="f" * 64, execution_mode="desktop_batch5", status="pending", step="pending", recipients=[], created_at=datetime.now(timezone.utc)))
        db.commit()
    reach._campaign_work("batch")

    def drain():
        for _ in range(20):
            if not queue:
                return
            fn, args = queue.pop(0)
            fn(*args)
        pytest.fail("queue did not terminate")

    yield reach, engine, sends, drain
    engine.dispose()


def confirm_batch(reach, engine):
    from sqlalchemy.orm import Session
    from app.models import CustomerReachCampaign
    with Session(engine) as db:
        campaign = db.get(CustomerReachCampaign, "batch")
        first = campaign.recipients[0]
        return reach.confirm_campaign_recipient("batch", reach.CampaignConfirmation(
            campaign_id="batch", recipient_id=first["recipient_id"], customer_key=first["customer_key"],
            content_fingerprint=campaign.content_fingerprint, confirm_batch=True,
            recipient_keys=[r["customer_key"] for r in campaign.recipients]), db)


def test_one_task_confirmation_runs_exactly_five_and_cannot_be_reused(batch):
    from sqlalchemy.orm import Session
    from app.models import CustomerReachCampaign
    from fastapi import HTTPException
    reach, engine, sends, drain = batch
    assert sends == []
    confirm_batch(reach, engine)
    drain()
    assert sends == [f"buyer-{i}" for i in range(5)]
    with Session(engine) as db:
        campaign = db.get(CustomerReachCampaign, "batch")
        assert campaign.status == "success"
        assert all(r["send_attempts"] == 1 for r in campaign.recipients)
        assert reach._campaign_view(campaign)["statistics"]["success_rate"] == 1
    with pytest.raises(HTTPException):
        confirm_batch(reach, engine)


def test_unknown_batch_rechecks_then_continues_without_resend(batch, monkeypatch):
    from sqlalchemy.orm import Session
    from app.models import CustomerReachCampaign
    reach, engine, sends, drain = batch

    def uncertain(self, task, recipient, update):
        update(claim_send=True)
        sends.append(recipient["nickname"])
        raise DesktopExecutionError("echo unavailable", may_have_sent=True)

    original = WinAppDesktop.send_customer
    monkeypatch.setattr(WinAppDesktop, "send_customer", uncertain)
    confirm_batch(reach, engine)
    drain()
    assert sends == ["buyer-0"]
    monkeypatch.setattr(WinAppDesktop, "verify_single_result", lambda *a: None)
    monkeypatch.setattr(WinAppDesktop, "send_customer", original)
    with Session(engine) as db:
        assert db.get(CustomerReachCampaign, "batch").status == "unknown"
        reach.recheck_single_result("batch", db)
    drain()
    assert sends == [f"buyer-{i}" for i in range(5)]
    with Session(engine) as db:
        assert db.get(CustomerReachCampaign, "batch").status == "success"


def test_changed_five_customer_scope_is_not_authorized(batch):
    from sqlalchemy.orm import Session
    from sqlalchemy.orm.attributes import flag_modified
    from app.models import CustomerReachCampaign
    reach, engine, sends, drain = batch
    confirm_batch(reach, engine)
    with Session(engine) as db:
        campaign = db.get(CustomerReachCampaign, "batch")
        campaign.recipients[1]["customer_key"] = "different-buyer"
        flag_modified(campaign, "recipients")
        db.commit()
    drain()
    assert sends == []
    with Session(engine) as db:
        assert db.get(CustomerReachCampaign, "batch").status == "paused"


def test_refusing_customer_is_not_sent_and_does_not_expand_scope(batch, monkeypatch):
    from sqlalchemy.orm import Session
    from app.models import CustomerReachCampaign
    reach, engine, sends, drain = batch

    def prepare(self, task, recipient, update):
        if recipient["sequence"] == 3:
            self._check_refusal("不要再发广告")
        return True

    monkeypatch.setattr(WinAppDesktop, "prepare_customer", prepare)
    confirm_batch(reach, engine)
    drain()
    assert sends == ["buyer-0", "buyer-1", "buyer-3", "buyer-4"]
    with Session(engine) as db:
        campaign = db.get(CustomerReachCampaign, "batch")
        assert campaign.status == "failed"
        assert campaign.recipients[2]["status"] == "failed"
        assert not campaign.recipients[2].get("send_attempts")


def test_read_only_unknown_failure_keeps_queue_stopped(batch, monkeypatch):
    from sqlalchemy.orm import Session
    from app.models import CustomerReachCampaign
    from fastapi import HTTPException
    reach, engine, sends, drain = batch

    def uncertain(self, task, recipient, update):
        update(claim_send=True)
        sends.append(recipient["nickname"])
        raise DesktopExecutionError("unknown", may_have_sent=True)

    monkeypatch.setattr(WinAppDesktop, "send_customer", uncertain)
    confirm_batch(reach, engine)
    drain()
    monkeypatch.setattr(WinAppDesktop, "verify_single_result", lambda *a: (_ for _ in ()).throw(DesktopExecutionError("still unknown", may_have_sent=True)))
    with Session(engine) as db:
        with pytest.raises(HTTPException):
            reach.recheck_single_result("batch", db)
        assert db.get(CustomerReachCampaign, "batch").status == "unknown"
    drain()
    assert sends == ["buyer-0"]


def test_front_occupation_samples_actual_foreground(monkeypatch):
    import ctypes
    import time
    adapter = WinAppDesktop()
    adapter._active_hwnds.add(123)
    monkeypatch.setattr(ctypes.windll.user32, "GetForegroundWindow", lambda: 123)
    updates = {}
    with adapter.measure_execution("prepare", lambda **kw: updates.update(kw)):
        time.sleep(0.08)
    timing = updates["timing"]
    assert 0 < timing["front_occupied_prepare_seconds"] <= timing["prepare_execution_seconds"]


def test_single_customer_placeholder_has_statistics_before_location():
    from datetime import datetime, timezone
    from app import customer_reach as reach
    from app.models import CustomerReachCampaign
    campaign = CustomerReachCampaign(id="single", execution_mode="desktop_single", customer_category="ordered",
        recipients=[{"target_only": True, "nickname": "buyer"}], created_at=datetime.now(timezone.utc))
    stats = reach._campaign_view(campaign)["statistics"]
    assert stats["customers"] == 1 and stats["success"] == 0 and stats["total_seconds"] == 0


def test_statistics_keeps_waiting_separate_from_front_occupation():
    from datetime import datetime, timedelta, timezone
    from app import customer_reach as reach
    from app.models import CustomerReachCampaign
    started = datetime(2026, 10, 25, tzinfo=timezone.utc)
    campaign = CustomerReachCampaign(execution_mode="desktop_batch5", customer_category="ordered", started_at=started,
        finished_at=started + timedelta(minutes=10), recipients=[
            {"status": status, "timing": {"prepare_execution_seconds": 5, "front_occupied_prepare_seconds": 2}}
            for status in ["success", "success", "success", "failed", "unknown"]])
    stats = reach._campaign_view(campaign)["statistics"]
    assert stats["total_seconds"] == 600
    assert stats["front_occupied_seconds"] == 10
    assert stats["average_processing_seconds"] == 5
    assert stats["success_rate"] == 0.6


def test_batch_confirmation_requires_a_locked_shop(batch):
    from sqlalchemy.orm import Session
    from sqlalchemy.orm.attributes import flag_modified
    from app.models import CustomerReachCampaign
    from fastapi import HTTPException
    reach, engine, sends, drain = batch
    with Session(engine) as db:
        campaign = db.get(CustomerReachCampaign, "batch")
        campaign.recipients[2]["shop_title"] = None
        flag_modified(campaign, "recipients")
        db.commit()
    with pytest.raises(HTTPException):
        confirm_batch(reach, engine)
    drain()
    assert sends == []


@pytest.mark.parametrize("prior_result", ["verified", "unknown"])
def test_new_batch_never_repeats_prior_same_content_send(batch, prior_result):
    from sqlalchemy.orm import Session
    from app.models import CustomerReachCampaign
    from datetime import datetime, timezone
    reach, engine, sends, drain = batch
    with Session(engine) as db:
        original = db.get(CustomerReachCampaign, "batch")
        row = dict(original.recipients[0], status="success" if prior_result == "verified" else "unknown",
                   send_attempts=1, send_result=prior_result)
        db.add(CustomerReachCampaign(id="prior", customer_category="ordered", message_text=original.message_text,
            product_url=original.product_url, content_fingerprint=original.content_fingerprint, execution_mode="desktop_batch5",
            status=row["status"], step="prior", recipients=[row], created_at=datetime.now(timezone.utc)))
        original.recipients = []
        original.status = "pending"
        db.commit()
    reach._campaign_work("batch")
    with Session(engine) as db:
        campaign = db.get(CustomerReachCampaign, "batch")
        if prior_result == "unknown":
            assert campaign.status == "failed"
        else:
            assert campaign.recipients[0]["status"] == "skipped"
            assert len(campaign.recipients) == 5
    assert sends == []


def test_wrong_shop_window_is_never_activated(monkeypatch):
    adapter = WinAppDesktop()
    adapter.shop_title = "expected"
    monkeypatch.setattr(adapter, "_native_windows", lambda: [{"hwnd": 123, "processId": 7, "title": "other-1688商家工作台"}])
    with pytest.raises(DesktopExecutionError, match="店铺"):
        adapter._activate(123)


@pytest.mark.parametrize("recognized", ["工作台", "订单详情"])
def test_business_tab_recovery_requires_verified_native_home_label(monkeypatch, recognized):
    from PIL import Image
    from io import BytesIO
    adapter = WinAppDesktop()
    image = BytesIO()
    Image.new("RGBA", (800, 600), "white").save(image, format="PNG")
    monkeypatch.setattr(adapter, "_capture", lambda *a: image.getvalue())
    monkeypatch.setattr(adapter, "_run", lambda *a, **kw: {"selector": "root", "x": 20, "y": 10, "width": 800, "height": 600})
    monkeypatch.setattr("app.customer_reach_desktop.subprocess.run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout=recognized.encode("utf-8")))
    monkeypatch.setattr(adapter, "_search", lambda *a: [{"name": "客户管理", "type": "Hyperlink", "selector": "entry"}])
    clicks = []
    monkeypatch.setattr(adapter, "_click_screen_point", lambda *a: clicks.append(a))
    if recognized == "工作台":
        assert adapter._restore_workbench_page(123)["selector"] == "entry"
        assert clicks == [((88, 36), 123)]
    else:
        with pytest.raises(DesktopExecutionError):
            adapter._restore_workbench_page(123)
        assert clicks == []


@pytest.mark.parametrize("verb,retried", [("search", True), ("send-keys", False)])
def test_only_read_queries_can_retry_timeout(monkeypatch, verb, retried):
    import subprocess
    adapter = WinAppDesktop()
    calls = []

    def run(*a, **kw):
        calls.append(kw["timeout"])
        if len(calls) == 1:
            raise subprocess.TimeoutExpired("winapp", 20)
        return SimpleNamespace(returncode=0, stdout='{}')

    monkeypatch.setattr("app.customer_reach_desktop.subprocess.run", run)
    if retried:
        adapter._run(verb, "probe", json_output=True)
        assert calls == [20, 60]
    else:
        with pytest.raises(DesktopExecutionError):
            adapter._run(verb, "probe", json_output=True)
        assert calls == [20]


def test_hidden_workbench_is_reused_without_launch(monkeypatch):
    adapter = WinAppDesktop()
    hidden = {"hwnd": 123, "processId": 7, "processName": "AliWorkbench", "title": "shop-1688商家工作台"}
    monkeypatch.setattr(adapter, "_run", lambda *a, **kw: [])
    monkeypatch.setattr(adapter, "_native_windows", lambda: [hidden], raising=False)
    assert adapter._windows(workbench=True) == hidden


def test_focus_activates_background_window_before_uia(monkeypatch):
    adapter = WinAppDesktop()
    events = []
    monkeypatch.setattr(adapter, "_activate", lambda hwnd: events.append("activate"), raising=False)
    monkeypatch.setattr(adapter, "_run", lambda *a, **kw: events.append(a[0]) or {"windows": [{"elements": [{"selector": "root"}]}]})
    import ctypes
    monkeypatch.setattr(ctypes.windll.user32, "IsIconic", lambda hwnd: False)
    monkeypatch.setattr(ctypes.windll.user32, "GetForegroundWindow", lambda: 123)
    adapter._focus(123)
    assert events[0] == "activate"


def test_foreground_denial_recovers_once_before_retry(monkeypatch):
    adapter = WinAppDesktop()
    calls = []
    results = iter([
        SimpleNamespace(returncode=1, stderr='{"error":{"code":"foreground_not_target"}}', stdout=""),
        SimpleNamespace(returncode=0, stderr="", stdout='{"matches": []}'),
    ])
    monkeypatch.setattr("app.customer_reach_desktop.subprocess.run", lambda *a, **kw: next(results))
    monkeypatch.setattr(adapter, "_focus", lambda hwnd: calls.append(hwnd))
    assert adapter._run("search", "客户管理", "-w", "123", json_output=True) == {"matches": []}
    assert calls == [123]


def test_unknown_verification_does_not_activate_for_screenshot(monkeypatch):
    adapter = WinAppDesktop()
    task = SimpleNamespace(message_text="body", product_url="https://detail.1688.com/offer/1.html")
    monkeypatch.setattr(adapter, "_chat_window", lambda: {"hwnd": 123})
    monkeypatch.setattr(adapter, "_document", lambda *a: ({}, task.message_text + " " + task.product_url))
    monkeypatch.setattr(adapter, "_focus", lambda *a: pytest.fail("read-only must not activate"))
    monkeypatch.setattr(adapter, "_run", lambda *a, **kw: pytest.fail("read-only must not capture the foreground screen"))
    adapter.verify_single_result(task, {"nickname": "buyer"}, lambda **kw: None)
