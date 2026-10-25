import pytest
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from PIL import Image, ImageDraw
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.customer_reach_desktop import DesktopExecutionError, WinAppDesktop, _nodes, _norm
from app.customer_reach import recover_customer_reach_tasks
from app.models import Base, CustomerReachTask


def test_search_nodes_remain_ephemeral_and_name_match_is_exact(monkeypatch):
    adapter = WinAppDesktop()
    results = [
        {"name": "旺旺洽谈", "type": "Button", "selector": "btn-live-1234"},
        {"name": "旺旺洽谈-历史", "type": "Text", "selector": "txt-live-5678"},
    ]
    monkeypatch.setattr(adapter, "_search", lambda _hwnd, _text, _type=None: results)
    node = adapter._one(99, "旺旺洽谈", "Button")
    assert node["selector"] == "btn-live-1234"
    assert list(_nodes({"matches": results})) == results
    assert _norm("新品\nhttps://detail.1688.com/offer/1") == "新品 https://detail.1688.com/offer/1"

    monkeypatch.setattr(adapter, "_search", lambda *_args: results + [dict(results[0], selector="btn-live-9999")])
    with pytest.raises(DesktopExecutionError, match="唯一识别"):
        adapter._one(99, "旺旺洽谈", "Button")


def test_reception_center_window_is_a_valid_client_window_without_title_switch(monkeypatch):
    adapter = WinAppDesktop()
    reception = {"hwnd": 123, "processName": "AliWorkbench", "title": "店铺名-接待中心"}
    monkeypatch.setattr(adapter, "_run", lambda *args, **kwargs: [reception])
    monkeypatch.setattr(adapter, "_search", lambda *_args: pytest.fail("must not infer a workbench switch control"))
    assert adapter._windows() == reception


def test_foreground_reception_window_wins_over_background_workbench(monkeypatch):
    adapter = WinAppDesktop()
    reception = {"hwnd": 123, "processName": "AliWorkbench", "title": "店铺名-接待中心", "isForeground": True}
    workbench = {"hwnd": 456, "processName": "AliWorkbench", "title": "店铺名-1688商家工作台", "isForeground": False}
    monkeypatch.setattr(adapter, "_run", lambda *args, **kwargs: [reception, workbench])
    assert adapter._windows() == reception


def test_search_treats_cli_no_match_as_empty_but_keeps_other_errors(monkeypatch):
    adapter = WinAppDesktop()
    monkeypatch.setattr(
        "app.customer_reach_desktop.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout='{"matchCount":0,"matches":[]}', stderr=""),
    )
    assert adapter._search(123, "not on this page") == []

    monkeypatch.setattr(
        "app.customer_reach_desktop.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout='{}', stderr="access denied"),
    )
    with pytest.raises(DesktopExecutionError):
        adapter._search(123, "not on this page")


def test_send_button_is_located_from_the_fresh_screenshot_and_live_document_bounds():
    image = Image.new("RGB", (1000, 900), "white")
    ImageDraw.Draw(image).rectangle((700, 650, 799, 681), fill=(37, 99, 235))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    bounds = {"x": 100, "y": 100, "width": 800, "height": 600}
    label = {"name": "发送", "type": "Text", "x": 744, "y": 655, "width": 30, "height": 20}
    point = WinAppDesktop._send_button_point(buffer.getvalue(), bounds, [label])
    assert 700 <= point[0] <= 799
    assert 650 <= point[1] <= 681

    ImageDraw.Draw(image).rectangle((500, 650, 599, 681), fill=(37, 99, 235))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    with pytest.raises(DesktopExecutionError, match="无法唯一定位"):
        WinAppDesktop._send_button_point(buffer.getvalue(), bounds, [label])
    with pytest.raises(DesktopExecutionError, match="UIA 未能唯一识别"):
        WinAppDesktop._send_button_point(buffer.getvalue(), bounds, [])


def test_unexpected_pre_send_executor_error_is_not_marked_unknown(monkeypatch):
    adapter = WinAppDesktop()

    def fail_before_send():
        raise ValueError("test failure")

    monkeypatch.setattr(adapter, "_chat_window", fail_before_send)
    task = SimpleNamespace(customer_nickname="买家", message_text="文案", product_url="https://detail.1688.com/offer/1.html")
    with pytest.raises(DesktopExecutionError) as error:
        adapter.send(task, lambda **_values: None)
    assert not error.value.may_have_sent


def test_customer_row_requires_visible_login_and_explicit_marketing_consent():
    authorized = {"type": "DataItem", "name": "张三", "children": [
        {"type": "Text", "name": "会员登录名：buyer-17"}, {"type": "Text", "name": "营销授权：已授权"},
    ]}
    ordered_only = {"type": "DataItem", "name": "李四", "children": [
        {"type": "Text", "name": "会员登录名：buyer-18"}, {"type": "Text", "name": "已成单客户"},
    ]}
    no_stable_id = {"type": "DataItem", "name": "王五", "children": [
        {"type": "Text", "name": "营销授权：已授权"},
    ]}
    assert WinAppDesktop._parse_customer_row(authorized, "已成单客户") == {
        "customer_key": "login:buyer-17", "nickname": "张三", "category": "已成单客户",
        "eligible": True, "authorization_evidence": "营销授权：已授权",
    }
    assert not WinAppDesktop._parse_customer_row(ordered_only, "已成单客户")["eligible"]
    assert not WinAppDesktop._parse_customer_row(no_stable_id, "已成单客户")["eligible"]


def test_restart_recovery_fails_pre_send_and_marks_sending_unknown():
    database_file = Path(__file__).parent / f"customer-reach-recovery-{uuid4()}.db"
    engine = create_engine(f"sqlite:///{database_file.as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        for status in ("preparing", "sending"):
            db.add(CustomerReachTask(
                id=status, customer_nickname="买家", message_text="文案", product_url="https://detail.1688.com/offer/1.html",
                content_fingerprint="f" * 64, execution_mode="desktop", status=status, step="执行中",
                created_at=datetime.now(timezone.utc),
            ))
        db.commit()
    try:
        recover_customer_reach_tasks(lambda: Session(engine))
        with Session(engine) as db:
            assert db.get(CustomerReachTask, "preparing").status == "failed"
            interrupted_send = db.get(CustomerReachTask, "sending")
            assert interrupted_send.status == "unknown"
            assert interrupted_send.send_result == "unknown"
    finally:
        engine.dispose()
        database_file.unlink(missing_ok=True)

def test_preview_mode_never_reaches_send(monkeypatch):
    adapter = WinAppDesktop()
    monkeypatch.setattr(adapter, '_chat_window', lambda: pytest.fail('preview must not reach chat/send operations'))
    with pytest.raises(DesktopExecutionError, match='禁止发送'):
        adapter.send(SimpleNamespace(execution_mode='desktop_preview'), lambda **v: None)


def test_checkpoint_stops_before_starting_next_command(monkeypatch):
    adapter = WinAppDesktop()
    def stop():
        raise RuntimeError('campaign stopped')
    adapter.checkpoint = stop
    monkeypatch.setattr('app.customer_reach_desktop.subprocess.run', lambda *a, **kw: pytest.fail('must stop before command'))
    with pytest.raises(RuntimeError, match='campaign stopped'):
        adapter._run('click', 'ephemeral-selector')


def test_one_filters_same_name_document_and_link(monkeypatch):
    adapter = WinAppDesktop()
    monkeypatch.setattr(adapter, '_search', lambda *a: [
        {'name': '客户管理', 'type': 'Document', 'selector': 'document'},
        {'name': '客户管理', 'type': 'Hyperlink', 'selector': 'link'},
    ])
    assert adapter._one(1, '客户管理', 'Hyperlink')['selector'] == 'link'


def test_preview_requires_proven_first_page(monkeypatch):
    adapter = WinAppDesktop()
    monkeypatch.setattr(adapter, '_one', lambda *a: {'isEnabled': True})
    monkeypatch.setattr(adapter, '_run', lambda *a, **kw: pytest.fail('must not inspect another page'))
    with pytest.raises(DesktopExecutionError, match='第一页'):
        adapter._first_customer(1, '已成单客户')

def test_preview_task_is_persisted_and_confirmation_is_rejected(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from app import customer_reach
    from app.models import CustomerReachCampaign
    engine = create_engine(f"sqlite:///{(tmp_path / 'preview.db').as_posix()}")
    Base.metadata.create_all(engine)
    monkeypatch.setenv('PERSONAL_WORKBENCH_CUSTOMER_REACH_MODE', 'desktop')
    monkeypatch.setattr(customer_reach._runner, 'submit', lambda *a: None)
    with Session(engine) as db:
        with pytest.raises(HTTPException) as rejected:
            customer_reach.create_campaign(customer_reach.CreateCampaign(customer_category='inquiry', message_text='ignored', preview_only=True), db)
        assert rejected.value.detail['code'] == 'preview_category_required'
        result = customer_reach.create_campaign(customer_reach.CreateCampaign(
            customer_category='ordered', message_text='ignored', preview_only=True), db)
        saved = db.get(CustomerReachCampaign, result['id'])
        assert saved.execution_mode == 'desktop_preview'
        assert saved.product_url == ''
        assert saved.message_text == 'X'
        with pytest.raises(HTTPException) as error:
            customer_reach.confirm_campaign_recipient(saved.id, customer_reach.CampaignConfirmation(
                campaign_id=saved.id, recipient_id='any', customer_key='any', content_fingerprint=saved.content_fingerprint), db)
        assert error.value.detail['code'] == 'preview_cannot_send'
        assert saved.status == 'pending'
    engine.dispose()

def test_preview_restores_existing_draft_without_send(monkeypatch):
    adapter = WinAppDesktop()
    original = '买家 原有草稿'
    current = [original]
    commands = []
    monkeypatch.setattr(adapter, '_preview_editor_snapshot', lambda *a: ((500, 500), current[0].casefold(), b'preview'))
    monkeypatch.setattr(adapter, '_click_screen_point', lambda *a: None)
    def run(*args, **kwargs):
        commands.append(args)
        if args[:2] == ('send-keys', 'X'):
            current[0] += 'X'
        if args[:2] == ('send-keys', 'backspace'):
            current[0] = current[0][:-1]
    monkeypatch.setattr(adapter, '_run', run)
    updates = []
    adapter._preview_draft(SimpleNamespace(message_text='X'), {'nickname': '买家'}, 1, lambda **v: updates.append(v))
    assert current[0] == original
    assert updates[-1]['preview_state']['restored'] is True
    assert updates[-1]['preview_state']['cleanup_required'] is False
    assert [c[1] for c in commands if c[0] == 'send-keys'] == ['ctrl+end', 'X', 'ctrl+end', 'backspace']


def test_preview_does_not_delete_if_other_content_changed(monkeypatch):
    adapter = WinAppDesktop()
    current = ['买家 原有草稿']
    commands = []
    monkeypatch.setattr(adapter, '_preview_editor_snapshot', lambda *a: ((500, 500), current[0].casefold(), b'preview'))
    monkeypatch.setattr(adapter, '_click_screen_point', lambda *a: None)
    def run(*args, **kwargs):
        commands.append(args)
        if args[:2] == ('send-keys', 'X'):
            current[0] += '新的其他内容X'
    monkeypatch.setattr(adapter, '_run', run)
    with pytest.raises(DesktopExecutionError, match='变化不止测试字符'):
        adapter._preview_draft(SimpleNamespace(message_text='X'), {'nickname': '买家'}, 1, lambda **v: None)
    assert not any(c[:2] == ('send-keys', 'backspace') for c in commands)

@pytest.mark.parametrize('button_y,valid', [(130, True), (340, False)])
def test_preview_binds_first_row_in_document_order_and_matching_action_row(monkeypatch, button_y, valid):
    adapter = WinAppDesktop()
    def node(kind, name='', **more):
        return {'type': kind, 'name': name, 'selector': kind + name, **more}
    first = node('DataItem', 'L6 首位买家 未流失', x=10, y=100, width=200, height=100,
                 children=[node('Text', 'L6'), node('Text', '首位买家'), node('Text', '未流失')])
    offscreen = node('DataItem', 'L6 其他买家 未流失', y=0, width=0, height=0)
    tables = [node('Table', x=10, width=1200, height=1000), node('Table', x=10, width=200, height=1000), node('Table', x=1000, width=150, height=1000)]
    calls = iter([tables, [first, offscreen], [node('DataItem', '操作', children=[node('Button', '旺旺洽谈', y=button_y, height=20)])]])
    monkeypatch.setattr(adapter, '_one', lambda h, text, kind: {'isEnabled': False} if text == '上一页' else {'selector': 'document'})
    monkeypatch.setattr(adapter, '_run', lambda *a, **kw: next(calls))
    if valid:
        result = adapter._first_customer(1, '已成单客户')
        assert result['nickname'] == '首位买家'
        assert result['customer_key'] == 'preview:first:首位买家'
        assert not result['eligible'] and result['authorization_evidence'] is None
    else:
        with pytest.raises(DesktopExecutionError, match='同行位置'):
            adapter._first_customer(1, '已成单客户')

@pytest.mark.parametrize('foreground,allowed', [(99, True), (100, False)])
def test_root_focus_error_is_allowed_only_for_verified_foreground(monkeypatch, foreground, allowed):
    import ctypes
    adapter = WinAppDesktop()
    monkeypatch.setattr(ctypes.windll.user32, 'IsIconic', lambda h: False)
    monkeypatch.setattr(ctypes.windll.user32, 'GetForegroundWindow', lambda: foreground)
    def run(*args, **kwargs):
        if args[0] == 'inspect':
            return {'windows': [{'elements': [{'selector': 'window-root'}]}]}
        raise DesktopExecutionError('focus 失败（focus_not_acquired）')
    monkeypatch.setattr(adapter, '_run', run)
    if allowed:
        adapter._focus(99)
    else:
        with pytest.raises(DesktopExecutionError):
            adapter._focus(99)

@pytest.mark.parametrize('domain,login,valid', [('air.1688.com','买家',True), ('air.1688.com','其他买家',False), ('other.example','买家',False)])
def test_generic_chat_document_requires_matching_trusted_panel_identity(monkeypatch, domain, login, valid):
    from urllib.parse import urlencode
    adapter = WinAppDesktop()
    def search(hwnd,text,kind=None):
        if text == '买家': return [{'type':'Text','name':'买家','selector':'label'}]
        if text == '千牛消息聊天': return [{'type':'Document','name':text,'selector':'chat'}]
        return [{'type':'Document','name':'1688商家版服务面板','selector':'panel','value':'https://'+domain+'/?'+urlencode({'chatLoginId':login})}]
    monkeypatch.setattr(adapter,'_search',search)
    monkeypatch.setattr(adapter,'_run',lambda *a,**kw:{'value':'买家 历史内容 原有草稿'})
    if valid:
        assert adapter._document(1,'买家')[0]['selector']=='chat'
    else:
        with pytest.raises(DesktopExecutionError,match='登录标识'):
            adapter._document(1,'买家')
