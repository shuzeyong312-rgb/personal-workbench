"""Single-customer outreach tasks; desktop execution stays outside collection code."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
import os
from types import SimpleNamespace
from threading import Lock
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import inspect, select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.database import get_db
from app.models import CustomerReachCampaign, CustomerReachTask

router = APIRouter(prefix="/api/customer-reach", tags=["customer-reach"])
_runner = ThreadPoolExecutor(max_workers=1, thread_name_prefix="customer-reach")
_creation_lock = Lock()
ACTIVE = ("pending", "locating", "preparing", "awaiting_confirmation", "sending", "paused")
CANCELLABLE = (*ACTIVE[:4], "paused")
DESKTOP_BATCH_LIMIT = 5


@router.get("/mode")
def get_mode():
    return {"mode": os.getenv("PERSONAL_WORKBENCH_CUSTOMER_REACH_MODE", "simulated")}


class CreateTask(BaseModel):
    customer_nickname: str = Field(min_length=1, max_length=255)
    message_text: str = Field(min_length=1, max_length=10000)
    product_url: str = Field(min_length=1, max_length=2048)


class Confirmation(BaseModel):
    task_id: str
    customer_nickname: str
    content_fingerprint: str


class CreateCampaign(BaseModel):
    customer_category: str = Field(pattern="^(ordered|inquiry)$")
    message_text: str = Field(min_length=1, max_length=10000)
    product_url: str = Field(default="", max_length=2048)
    preview_only: bool = False
    single_customer_nickname: str | None = Field(default=None, min_length=1, max_length=255)


class CampaignConfirmation(BaseModel):
    campaign_id: str
    recipient_id: str
    customer_key: str
    content_fingerprint: str


class CampaignView(BaseModel):
    id: str
    customer_category: str
    message_text: str
    product_url: str
    content_fingerprint: str
    execution_mode: str
    status: str
    step: str
    recipients: list[dict]
    current_recipient_id: str | None
    error_reason: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class TaskView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    customer_nickname: str
    message_text: str
    product_url: str
    content_fingerprint: str
    execution_mode: str
    status: str
    step: str
    matched_customer: str | None
    draft_verified: bool | None
    send_result: str | None
    error_reason: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


def _fingerprint(message: str, url: str) -> str:
    return sha256((message + "\n" + url).encode("utf-8")).hexdigest()


def recover_customer_reach_tasks(session_factory) -> None:
    now = datetime.now(timezone.utc)
    with session_factory() as db:
        if not inspect(db.get_bind()).has_table(CustomerReachTask.__tablename__):
            return
        for task in db.scalars(select(CustomerReachTask).where(CustomerReachTask.status.in_(("locating", "preparing", "sending")))):
            task.status = "unknown" if task.status == "sending" else "failed"
            task.step = "重启后发送结果需核实" if task.status == "unknown" else "执行器中断"
            task.send_result = "unknown" if task.status == "unknown" else task.send_result
            task.error_reason = "服务中断后未自动重试；发送状态需人工核对" if task.status == "unknown" else "服务中断，未自动恢复桌面操作"
            task.finished_at = now
        pending = list(db.scalars(select(CustomerReachTask.id).where(CustomerReachTask.status == "pending").order_by(CustomerReachTask.created_at)))
        campaign_ids = []
        if inspect(db.get_bind()).has_table(CustomerReachCampaign.__tablename__):
            for campaign in db.scalars(select(CustomerReachCampaign)):
                if campaign.status == "sending":
                    campaign.status = "unknown"
                    campaign.step = "服务重启后发送结果需人工核实"
                    campaign.error_reason = "服务中断后不自动重发，请人工核对消息记录"
                    campaign.finished_at = now
                    if campaign.current_recipient_id:
                        recipient = _campaign_recipient(campaign, campaign.current_recipient_id)
                        if recipient:
                            recipient.update(status="unknown", send_result="unknown", error_reason=campaign.error_reason,
                                             step=campaign.step, processed_at=now.isoformat())
                            flag_modified(campaign, "recipients")
                elif campaign.status in {"locating", "preparing"}:
                    campaign.status = "failed"
                    campaign.step = "服务重启后桌面任务已停止"
                    campaign.error_reason = "服务中断，桌面步骤未自动恢复"
                    campaign.finished_at = now
                    if campaign.current_recipient_id:
                        recipient = _campaign_recipient(campaign, campaign.current_recipient_id)
                        if recipient and recipient["status"] == "preparing":
                            recipient.update(status="failed", error_reason=campaign.error_reason, step=campaign.step,
                                             processed_at=now.isoformat())
                            flag_modified(campaign, "recipients")
                elif campaign.status in {"pending", "awaiting_confirmation"}:
                    campaign_ids.append(campaign.id)
        db.commit()
    for task_id in pending:
        _runner.submit(_work, task_id)
    for campaign_id in campaign_ids:
        _runner.submit(_campaign_work, campaign_id)


def _view(task: CustomerReachTask) -> dict:
    return {key: getattr(task, key) for key in TaskView.model_fields}


def _work(task_id: str) -> None:
    # Open short sessions so UI actions can update the task while the worker waits.
    from app.database import engine

    def patch_task(**values):
        with Session(engine) as db:
            task = db.get(CustomerReachTask, task_id)
            if task is None or task.status in {"cancelled", "paused"}:
                raise RuntimeError("task stopped")
            db.execute(update(CustomerReachTask).where(CustomerReachTask.id == task_id).values(**values))
            db.commit()

    with Session(engine) as db:
        task = db.get(CustomerReachTask, task_id)
        if task is None or task.status != "pending":
            return
        task.status = "locating"
        task.step = "搜索并核对客户"
        task.started_at = datetime.now(timezone.utc)
        execution_mode = task.execution_mode
        customer_nickname = task.customer_nickname
        task_data = SimpleNamespace(id=task.id, customer_nickname=customer_nickname, message_text=task.message_text,
                                    product_url=task.product_url, execution_mode=execution_mode)
        db.commit()

    # The safe default is a deterministic simulator; the live adapter is opt-in.
    if execution_mode == "simulated":
        patch_task(status="preparing", step="准备消息草稿", matched_customer=customer_nickname)
        patch_task(status="awaiting_confirmation", step="核对客户和草稿后等待确认", draft_verified=True)
    else:
        from app.customer_reach_desktop import DesktopExecutionError, WinAppDesktop

        try:
            WinAppDesktop().prepare(task_data, patch_task)
        except DesktopExecutionError as exc:
            with Session(engine) as db:
                failed = db.get(CustomerReachTask, task_id)
                if failed and failed.status in {"locating", "preparing"}:
                    failed.status = "failed"
                    failed.step = "桌面执行已停止"
                    failed.error_reason = str(exc)[:1000]
                    failed.finished_at = datetime.now(timezone.utc)
                    db.commit()
        except RuntimeError as exc:
            if str(exc) != "task stopped":
                with Session(engine) as db:
                    failed = db.get(CustomerReachTask, task_id)
                    if failed and failed.status in {"locating", "preparing"}:
                        failed.status = "failed"
                        failed.step = "桌面执行异常"
                        failed.error_reason = "桌面执行遇到未预期错误"
                        failed.finished_at = datetime.now(timezone.utc)
                        db.commit()
        except Exception:
            with Session(engine) as db:
                failed = db.get(CustomerReachTask, task_id)
                if failed and failed.status in {"locating", "preparing"}:
                    failed.status = "failed"
                    failed.step = "桌面执行异常"
                    failed.error_reason = "桌面执行遇到未预期错误"
                    failed.finished_at = datetime.now(timezone.utc)
                    db.commit()
        return



def _finish_send(task_id: str) -> None:
    from app.database import engine

    with Session(engine) as db:
        task = db.get(CustomerReachTask, task_id)
        if task is None or task.status != "sending":
            return
        if task.execution_mode == "simulated":
            task.status = "success"
            task.step = "模拟发送完成；未操作工作台"
            task.send_result = "simulated"
            task.finished_at = datetime.now(timezone.utc)
            db.commit()
            return
        task_data = SimpleNamespace(id=task.id, customer_nickname=task.customer_nickname,
                                    message_text=task.message_text, product_url=task.product_url,
                                    execution_mode=task.execution_mode)
    from app.customer_reach_desktop import DesktopExecutionError, WinAppDesktop

    def update_task(**values):
        with Session(engine) as db:
            db.execute(update(CustomerReachTask).where(CustomerReachTask.id == task_id, CustomerReachTask.status == "sending").values(**values))
            db.commit()

    try:
        WinAppDesktop().send(task_data, update_task)
    except DesktopExecutionError as exc:
        with Session(engine) as db:
            task = db.get(CustomerReachTask, task_id)
            if task and task.status == "sending":
                task.status = "unknown" if exc.may_have_sent else "failed"
                task.step = "发送结果需人工核实" if exc.may_have_sent else "工作台明确报告发送失败" if exc.send_failed else "发送前核验失败"
                task.send_result = "unknown" if exc.may_have_sent else "failed" if exc.send_failed else "not_sent"
                task.error_reason = str(exc)[:1000]
                task.finished_at = datetime.now(timezone.utc)
                db.commit()
        return
    except Exception:
        with Session(engine) as db:
            task = db.get(CustomerReachTask, task_id)
            if task and task.status == "sending":
                task.status = "unknown"
                task.step = "发送结果需人工核实"
                task.send_result = "unknown"
                task.error_reason = "发送后遇到未预期错误，请人工核对消息记录"
                task.finished_at = datetime.now(timezone.utc)
                db.commit()
        return
    update_task(status="success", step="聊天记录回显已核验", send_result="verified", finished_at=datetime.now(timezone.utc))


@router.post("/tasks", status_code=201)
def create_task(body: CreateTask, db: Session = Depends(get_db)):
    nickname = body.customer_nickname.strip()
    message = body.message_text.strip()
    url = body.product_url.strip()
    if not nickname or not message or not url or not url.startswith(("https://", "http://")):
        raise HTTPException(422, detail={"code": "invalid_task", "message": "请填写客户、文案和有效商品链接"})
    mode = os.getenv("PERSONAL_WORKBENCH_CUSTOMER_REACH_MODE", "simulated")
    if mode not in {"simulated", "desktop"}:
        raise HTTPException(500, detail={"code": "invalid_executor_mode", "message": "客户触达执行模式配置无效"})
    task = CustomerReachTask(id=str(uuid4()), customer_nickname=nickname, message_text=message, product_url=url,
        content_fingerprint=_fingerprint(message, url), execution_mode=mode, status="pending", step="等待执行", created_at=datetime.now(timezone.utc))
    with _creation_lock:
        if db.scalar(select(CustomerReachTask.id).where(CustomerReachTask.status.in_(ACTIVE)).limit(1)):
            raise HTTPException(409, detail={"code": "task_in_progress", "message": "已有客户触达任务正在执行"})
        db.add(task)
        db.commit()
        db.refresh(task)
        _runner.submit(_work, task.id)
    return _view(task)


@router.get("/tasks")
def list_tasks(db: Session = Depends(get_db)):
    return [_view(task) for task in db.scalars(select(CustomerReachTask).order_by(CustomerReachTask.created_at.desc()).limit(100))]


@router.get("/tasks/{task_id}")
def get_task(task_id: str, db: Session = Depends(get_db)):
    task = db.get(CustomerReachTask, task_id)
    if task is None:
        raise HTTPException(404, detail={"code": "task_not_found", "message": "任务不存在"})
    return _view(task)


@router.post("/tasks/{task_id}/confirm")
def confirm_task(task_id: str, body: Confirmation, db: Session = Depends(get_db)):
    task = db.get(CustomerReachTask, task_id)
    if task is None:
        raise HTTPException(404, detail={"code": "task_not_found", "message": "任务不存在"})
    if body.task_id != task.id or body.content_fingerprint != task.content_fingerprint or body.customer_nickname != task.matched_customer:
        raise HTTPException(409, detail={"code": "confirmation_mismatch", "message": "客户或内容与本次任务不匹配"})
    changed = db.execute(update(CustomerReachTask).where(CustomerReachTask.id == task_id,
        CustomerReachTask.status == "awaiting_confirmation", CustomerReachTask.draft_verified.is_(True)).values(
            status="sending", step="用户已确认，发送中"))
    db.commit()
    if not changed.rowcount:
        raise HTTPException(409, detail={"code": "confirmation_used", "message": "任务已确认、暂停或结束"})
    db.refresh(task)
    _runner.submit(_finish_send, task_id)
    return _view(task)


@router.post("/tasks/{task_id}/pause")
def pause_task(task_id: str, db: Session = Depends(get_db)):
    task = db.get(CustomerReachTask, task_id)
    if task is None:
        raise HTTPException(404, detail={"code": "task_not_found", "message": "任务不存在"})
    if task.status not in ACTIVE[:-2]:
        raise HTTPException(409, detail={"code": "task_not_pausable", "message": "当前任务状态不能暂停"})
    task.paused_from_status = task.status
    task.status = "paused"
    task.step = "已暂停"
    db.commit()
    return get_task(task_id, db)


@router.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: str, db: Session = Depends(get_db)):
    changed = db.execute(update(CustomerReachTask).where(CustomerReachTask.id == task_id,
        CustomerReachTask.status.in_(CANCELLABLE)).values(status="cancelled", step="已取消", finished_at=datetime.now(timezone.utc)))
    db.commit()
    if not changed.rowcount:
        raise HTTPException(409, detail={"code": "task_not_cancellable", "message": "发送已开始或任务已结束，不能取消"})
    return get_task(task_id, db)


@router.post("/tasks/{task_id}/resume")
def resume_task(task_id: str, db: Session = Depends(get_db)):
    task = db.get(CustomerReachTask, task_id)
    if task is None:
        raise HTTPException(404, detail={"code": "task_not_found", "message": "任务不存在"})
    if task.status != "paused":
        raise HTTPException(409, detail={"code": "task_not_paused", "message": "任务当前未暂停"})
    previous = task.paused_from_status
    task.paused_from_status = None
    task.status = "awaiting_confirmation" if previous == "awaiting_confirmation" else "pending"
    task.step = "核对客户和草稿后等待确认" if task.status == "awaiting_confirmation" else "等待执行"
    db.commit()
    if task.status == "pending":
        _runner.submit(_work, task.id)
    return _view(task)


@router.get("/tasks/{task_id}/screenshot")
def get_screenshot(task_id: str, db: Session = Depends(get_db)):
    task = db.get(CustomerReachTask, task_id)
    if task is None:
        raise HTTPException(404, detail={"code": "task_not_found", "message": "任务不存在"})
    if not task.screenshot:
        raise HTTPException(404, detail={"code": "screenshot_unavailable", "message": "当前没有运行时截图"})
    return Response(task.screenshot, media_type="image/png")


def _campaign_view(campaign: CustomerReachCampaign) -> dict:
    return {key: getattr(campaign, key) for key in CampaignView.model_fields}


def _campaign_update(campaign_id: str, **values) -> bool:
    from app.database import engine

    with Session(engine) as db:
        campaign = db.get(CustomerReachCampaign, campaign_id)
        if campaign is None or campaign.status in {"cancelled", "paused"}:
            return False
        claim_send = values.pop("claim_send", False)
        if claim_send:
            recipient = _campaign_recipient(campaign, campaign.current_recipient_id)
            if campaign.status != "sending" or not recipient or recipient.get("send_attempts", 0):
                raise RuntimeError("send already claimed or task not sending")
            recipient["send_attempts"] = 1
            recipient["send_claimed_at"] = datetime.now(timezone.utc).isoformat()
            flag_modified(campaign, "recipients")
        preview_state = values.pop("preview_state", None)
        if preview_state is not None and campaign.current_recipient_id:
            recipient = _campaign_recipient(campaign, campaign.current_recipient_id)
            if recipient:
                recipient["preview_state"] = preview_state
                flag_modified(campaign, "recipients")
        timing = values.pop("timing", None)
        if timing is not None and campaign.current_recipient_id:
            recipient = _campaign_recipient(campaign, campaign.current_recipient_id)
            if recipient:
                recipient.setdefault("timing", {}).update(timing)
                flag_modified(campaign, "recipients")
        for key, value in values.items():
            setattr(campaign, key, value)
        db.commit()
        return True


def _campaign_recipient(campaign: CustomerReachCampaign, recipient_id: str) -> dict | None:
    return next((row for row in campaign.recipients if row["recipient_id"] == recipient_id), None)


def _campaign_work(campaign_id: str) -> None:
    from app.database import engine

    with Session(engine) as db:
        campaign = db.get(CustomerReachCampaign, campaign_id)
        if campaign is None or campaign.status not in {"pending", "awaiting_confirmation"}:
            return
        if campaign.status == "pending" and (not campaign.recipients or campaign.recipients[0].get("target_only")):
            campaign.status = "locating"
            campaign.step = "进入客户管理并读取客户列表"
        campaign.started_at = campaign.started_at or datetime.now(timezone.utc)
        category = campaign.customer_category
        mode = campaign.execution_mode
        existing_recipients = list(campaign.recipients)
        db.commit()

    def update_campaign(**values):
        if not _campaign_update(campaign_id, **values):
            raise RuntimeError("campaign stopped")

    expected_single = existing_recipients[0]["nickname"] if mode == "desktop_single" and existing_recipients and existing_recipients[0].get("target_only") else None
    if expected_single:
        existing_recipients = []
    if existing_recipients:
        rows = []
        recipients = existing_recipients
    elif mode == "simulated":
        rows = [
            {"customer_key": "simulated-buyer-1", "nickname": "模拟客户 1", "category": category,
             "eligible": True, "authorization_evidence": "模拟：明确授权"},
            {"customer_key": "simulated-buyer-2", "nickname": "模拟客户 2", "category": category,
             "eligible": True, "authorization_evidence": "模拟：明确授权"},
            {"customer_key": "simulated-buyer-skipped", "nickname": "模拟客户（无授权）", "category": category,
             "eligible": False, "authorization_evidence": None},
        ]
    else:
        from app.customer_reach_desktop import DesktopExecutionError, WinAppDesktop

        try:
            adapter = WinAppDesktop()
            rows = adapter.list_customers(category, update_campaign, first_only=True) if mode in {"desktop_preview", "desktop_single"} else adapter.list_customers(category, update_campaign, eligible_limit=DESKTOP_BATCH_LIMIT if mode == "desktop_batch5" else None, test_scope=mode == "desktop_batch5")
            if mode == "desktop_single":
                if len(rows) != 1 or rows[0]["nickname"] != expected_single:
                    raise DesktopExecutionError("第一页首位客户与本次指定对象不一致，未更换客户")
        except RuntimeError as exc:
            if str(exc) != "campaign stopped":
                reason = str(exc)[:1000] if isinstance(exc, DesktopExecutionError) else "桌面执行遇到未预期错误"
                _campaign_update(campaign_id, status="failed", step="读取客户列表失败", error_reason=reason, finished_at=datetime.now(timezone.utc))
            return
        except Exception as exc:
            reason = str(exc)[:1000] if isinstance(exc, DesktopExecutionError) else "桌面执行遇到未预期错误"
            _campaign_update(campaign_id, status="failed", step="读取客户列表失败", error_reason=reason, finished_at=datetime.now(timezone.utc))
            return

    if not existing_recipients:
        seen: set[str] = set()
        recipients = []
        eligible_count = 0
        for sequence, row in enumerate(rows, 1):
            key = str(row.get("customer_key", "")).strip()
            nickname = str(row.get("nickname", "")).strip()
            category_value = row.get("category", category)
            explicit_evidence = str(row.get("authorization_evidence") or "").strip()
            eligible = bool(key and nickname) if mode in {"desktop_preview", "desktop_single", "desktop_batch5"} else row.get("eligible") is True and bool(explicit_evidence)
            if mode == "desktop_single":
                explicit_evidence = "用户指定此客户的一次测试授权；发送前检查明确拒收，不代表客户营销同意"
            duplicate = not key or key in seen
            if key:
                seen.add(key)
            if eligible and not duplicate:
                eligible_count += 1
            within_limit = mode != "desktop_batch5" or eligible_count <= DESKTOP_BATCH_LIMIT
            recipients.append({
                "recipient_id": str(uuid4()), "customer_key": key,
                "nickname": nickname or "身份不可识别", "category": category_value,
                "sequence": sequence, "eligible": eligible and not duplicate and within_limit,
                "authorization_evidence": explicit_evidence if eligible else None,
                "status": "pending" if eligible and not duplicate and within_limit else "skipped",
                "step": "等待处理" if eligible and not duplicate and within_limit else "已达到本次 5 位上限，未发送" if eligible and not duplicate else "缺少稳定身份、明确授权或重复记录，已跳过",
                "matched_customer": None, "draft_verified": None, "send_result": None,
                "error_reason": "本次连续测试仅处理前 5 位符合条件客户" if eligible and not duplicate and not within_limit else "重复或缺少稳定客户标识" if duplicate else None,
                "processed_at": None,
            })
        if not _campaign_update(campaign_id, recipients=recipients, step=f"读取到 {len(recipients)} 位客户，开始按顺序核对"):
            return

    for initial in recipients:
        recipient_id = initial["recipient_id"]
        with Session(engine) as db:
            campaign = db.get(CustomerReachCampaign, campaign_id)
            if campaign is None or campaign.status in {"paused", "cancelled"}:
                return
            recipient = _campaign_recipient(campaign, recipient_id)
            if not recipient or recipient["status"] not in {"pending", "awaiting_confirmation"} or not recipient["eligible"]:
                continue
            ready = recipient["status"] == "awaiting_confirmation"
            campaign.current_recipient_id = recipient_id
            campaign.status = "awaiting_confirmation" if ready else "locating"
            campaign.step = f"等待第 {recipient['sequence']} 位客户确认" if ready else f"定位第 {recipient['sequence']} 位客户：{recipient['nickname']}"
            if not ready:
                recipient["status"] = "preparing"
                recipient["step"] = "定位并核对客户"
                recipient["timing"] = {"locating_started_at": datetime.now(timezone.utc).isoformat()}
            flag_modified(campaign, "recipients")
            db.commit()
            task_data = SimpleNamespace(id=campaign.id, customer_nickname=recipient["nickname"], message_text=campaign.message_text,
                product_url=campaign.product_url, execution_mode=campaign.execution_mode)

        if ready:
            pass
        elif mode == "simulated":
            with Session(engine) as db:
                campaign = db.get(CustomerReachCampaign, campaign_id)
                if campaign is None or campaign.status in {"paused", "cancelled"}:
                    return
                recipient = _campaign_recipient(campaign, recipient_id)
                recipient.update(status="awaiting_confirmation", step="模拟身份和草稿核对通过，等待本客户确认",
                                 matched_customer=recipient["nickname"], draft_verified=True)
                campaign.status = "awaiting_confirmation"
                campaign.step = f"等待第 {recipient['sequence']} 位客户的单独确认"
                flag_modified(campaign, "recipients")
                db.commit()
        else:
            from app.customer_reach_desktop import DesktopExecutionError, WinAppDesktop
            try:
                verified = WinAppDesktop().prepare_customer(task_data, recipient, update_campaign) is not False
                with Session(engine) as db:
                    campaign = db.get(CustomerReachCampaign, campaign_id)
                    if campaign is None or campaign.status in {"paused", "cancelled"}:
                        return
                    recipient = _campaign_recipient(campaign, recipient_id)
                    recipient.update(status="awaiting_confirmation", step="身份和可见草稿已核验，等待本客户确认" if verified else "首位客户会话已核对，草稿待验收",
                                     matched_customer=recipient["nickname"], draft_verified=verified)
                    recipient.setdefault("timing", {})["awaiting_confirmation_at"] = datetime.now(timezone.utc).isoformat()
                    campaign.status = "awaiting_confirmation"
                    campaign.step = "非发送草稿已核验并清理；可跳过结束任务" if mode == "desktop_preview" and verified else f"等待第 {recipient['sequence']} 位客户的单独确认"
                    flag_modified(campaign, "recipients")
                    db.commit()
            except RuntimeError as exc:
                if str(exc) == "campaign stopped":
                    return
                with Session(engine) as db:
                    campaign = db.get(CustomerReachCampaign, campaign_id)
                    if campaign and campaign.status not in {"paused", "cancelled"}:
                        recipient = _campaign_recipient(campaign, recipient_id)
                        recipient.update(status="failed", step="桌面执行停止", error_reason=str(exc)[:1000] if isinstance(exc, DesktopExecutionError) else "桌面执行遇到未预期错误", processed_at=datetime.now(timezone.utc).isoformat())
                        flag_modified(campaign, "recipients")
                        db.commit()
                continue
            except Exception as exc:
                with Session(engine) as db:
                    campaign = db.get(CustomerReachCampaign, campaign_id)
                    if campaign and campaign.status not in {"paused", "cancelled"}:
                        recipient = _campaign_recipient(campaign, recipient_id)
                        recipient.update(status="failed", step="桌面执行停止", error_reason=str(exc)[:1000] if isinstance(exc, DesktopExecutionError) else "桌面执行遇到未预期错误",
                                         processed_at=datetime.now(timezone.utc).isoformat())
                        flag_modified(campaign, "recipients")
                        db.commit()
                continue

        return

    with Session(engine) as db:
        campaign = db.get(CustomerReachCampaign, campaign_id)
        failed = campaign and any(row["status"] == "failed" for row in campaign.recipients)
    _campaign_update(campaign_id, status="failed" if failed else "success",
                     step="存在客户执行失败，请查看逐客户原因" if failed else "队列处理完成；每位客户均已核验或记录为跳过", current_recipient_id=None,
                     finished_at=datetime.now(timezone.utc))


def _campaign_send(campaign_id: str, recipient_id: str) -> None:
    from app.database import engine

    with Session(engine) as db:
        campaign = db.get(CustomerReachCampaign, campaign_id)
        recipient = _campaign_recipient(campaign, recipient_id) if campaign else None
        if campaign is None or recipient is None or campaign.status != "sending" or recipient["status"] != "sending":
            return
        task_data = SimpleNamespace(id=campaign.id, customer_nickname=recipient["nickname"], message_text=campaign.message_text,
            product_url=campaign.product_url, execution_mode=campaign.execution_mode)
        recipient_data = dict(recipient)
        mode = campaign.execution_mode

    def update_campaign(**values):
        if not _campaign_update(campaign_id, **values):
            raise RuntimeError("campaign stopped")

    if mode == "simulated":
        send_result, error_reason = "simulated", None
    else:
        from app.customer_reach_desktop import DesktopExecutionError, WinAppDesktop
        try:
            WinAppDesktop().send_customer(task_data, recipient_data, update_campaign)
            send_result, error_reason = "verified", None
        except DesktopExecutionError as exc:
            send_result = "unknown" if exc.may_have_sent else "failed" if exc.send_failed else "not_sent"
            error_reason = str(exc)[:1000]
        except Exception:
            send_result, error_reason = "unknown", "发送后遇到未预期错误，请人工核对消息记录"

    continue_queue = False
    with Session(engine) as db:
        campaign = db.get(CustomerReachCampaign, campaign_id)
        if campaign is None or campaign.status != "sending":
            return
        recipient = _campaign_recipient(campaign, recipient_id)
        recipient.update(status="unknown" if send_result == "unknown" else "success" if send_result in {"simulated", "verified"} else "failed",
                         step="发送结果需人工核实" if send_result == "unknown" else "聊天记录回显已核验" if send_result == "verified" else "模拟完成，未发送" if send_result == "simulated" else "未发送或明确失败",
                         send_result=send_result, error_reason=error_reason, processed_at=datetime.now(timezone.utc).isoformat())
        flag_modified(campaign, "recipients")
        if send_result == "unknown":
            campaign.status, campaign.step, campaign.error_reason = "unknown", "发送结果未知，已停止队列且不会重发", error_reason
            campaign.finished_at = datetime.now(timezone.utc)
        elif mode == "desktop_single":
            campaign.status = "success" if send_result == "verified" else "failed"
            campaign.step = "单客一次发送完成，任务已结束" if send_result == "verified" else "单客发送未完成，任务已停止"
            campaign.error_reason = error_reason
            campaign.finished_at = datetime.now(timezone.utc)
        else:
            campaign.current_recipient_id = None
            campaign.status = "pending"
            campaign.step = "继续下一位未处理客户"
            continue_queue = True
        db.commit()
    if continue_queue:
        _runner.submit(_campaign_work, campaign_id)


@router.post("/campaigns", status_code=201)
def create_campaign(body: CreateCampaign, db: Session = Depends(get_db)):
    message, url = body.message_text.strip(), body.product_url.strip()
    if not message or (not body.preview_only and (not url or not url.startswith(("https://", "http://")))):
        raise HTTPException(422, detail={"code": "invalid_campaign", "message": "请填写文案和有效商品链接"})
    mode = os.getenv("PERSONAL_WORKBENCH_CUSTOMER_REACH_MODE", "simulated")
    if mode not in {"simulated", "desktop"}:
        raise HTTPException(500, detail={"code": "invalid_executor_mode", "message": "客户触达执行模式配置无效"})
    if body.preview_only:
        if body.customer_category != "ordered":
            raise HTTPException(422, detail={"code": "preview_category_required", "message": "非发送验收仅处理已成单客户第一页首位客户"})
        if mode != "desktop":
            raise HTTPException(409, detail={"code": "desktop_required", "message": "非发送实机验收需要 desktop 执行器"})
        mode, message, url = "desktop_preview", "X", ""
    if body.single_customer_nickname is not None:
        if mode != "desktop" or body.preview_only or body.customer_category != "ordered":
            raise HTTPException(422, detail={"code": "invalid_single_test", "message": "单客测试必须使用已成单客户和 desktop 模式"})
        mode = "desktop_single"
    elif mode == "desktop":
        mode = "desktop_batch5"
    with _creation_lock:
        if db.scalar(select(CustomerReachTask.id).where(CustomerReachTask.status.in_(ACTIVE)).limit(1)) or db.scalar(select(CustomerReachCampaign.id).where(CustomerReachCampaign.status.in_(ACTIVE)).limit(1)):
            raise HTTPException(409, detail={"code": "task_in_progress", "message": "已有客户触达任务正在执行"})
        campaign = CustomerReachCampaign(id=str(uuid4()), customer_category=body.customer_category, message_text=message, product_url=url,
            content_fingerprint=_fingerprint(message, url), execution_mode=mode, status="pending", step="等待执行", recipients=[],
            created_at=datetime.now(timezone.utc))
        if mode == "desktop_single":
            campaign.recipients = [{"target_only": True, "nickname": body.single_customer_nickname.strip()}]
        db.add(campaign)
        db.commit()
        db.refresh(campaign)
        _runner.submit(_campaign_work, campaign.id)
    return _campaign_view(campaign)


@router.get("/campaigns")
def list_campaigns(db: Session = Depends(get_db)):
    return [_campaign_view(item) for item in db.scalars(select(CustomerReachCampaign).order_by(CustomerReachCampaign.created_at.desc()).limit(100))]


@router.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: str, db: Session = Depends(get_db)):
    campaign = db.get(CustomerReachCampaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, detail={"code": "campaign_not_found", "message": "推广任务不存在"})
    return _campaign_view(campaign)


@router.post("/campaigns/{campaign_id}/confirm")
def confirm_campaign_recipient(campaign_id: str, body: CampaignConfirmation, db: Session = Depends(get_db)):
    campaign = db.get(CustomerReachCampaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, detail={"code": "campaign_not_found", "message": "推广任务不存在"})
    if campaign.execution_mode == "desktop_preview":
        raise HTTPException(409, detail={"code": "preview_cannot_send", "message": "非发送验收任务禁止发送"})
    recipient = _campaign_recipient(campaign, body.recipient_id)
    if body.campaign_id != campaign.id or body.content_fingerprint != campaign.content_fingerprint or not recipient or recipient["customer_key"] != body.customer_key or campaign.current_recipient_id != body.recipient_id:
        raise HTTPException(409, detail={"code": "confirmation_mismatch", "message": "客户或内容与当前推广任务不匹配"})
    if campaign.status != "awaiting_confirmation" or recipient["status"] != "awaiting_confirmation" or recipient["draft_verified"] is not True or recipient["matched_customer"] != recipient["nickname"]:
        raise HTTPException(409, detail={"code": "confirmation_used", "message": "当前客户未完成核验、已确认或任务已暂停"})
    changed = db.execute(update(CustomerReachCampaign).where(
        CustomerReachCampaign.id == campaign_id,
        CustomerReachCampaign.status == "awaiting_confirmation",
        CustomerReachCampaign.current_recipient_id == body.recipient_id,
    ).values(status="sending", step=f"第 {recipient['sequence']} 位客户发送中"))
    if not changed.rowcount:
        db.rollback()
        raise HTTPException(409, detail={"code": "confirmation_used", "message": "当前客户已确认或任务状态已变化"})
    recipient["status"], recipient["step"] = "sending", "用户已单独确认，发送中"
    recipient.setdefault("timing", {})["confirmed_at"] = datetime.now(timezone.utc).isoformat()
    flag_modified(campaign, "recipients")
    db.commit()
    db.refresh(campaign)
    _runner.submit(_campaign_send, campaign_id, body.recipient_id)
    return _campaign_view(campaign)


@router.post("/campaigns/{campaign_id}/pause")
def pause_campaign(campaign_id: str, db: Session = Depends(get_db)):
    campaign = db.get(CustomerReachCampaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, detail={"code": "campaign_not_found", "message": "推广任务不存在"})
    if campaign.status in {"sending", "success", "failed", "unknown", "cancelled", "paused"}:
        raise HTTPException(409, detail={"code": "campaign_not_pausable", "message": "当前状态不能暂停"})
    campaign.status, campaign.step = "paused", "已暂停；恢复后从未完成客户继续"
    db.commit()
    return _campaign_view(campaign)


@router.post("/campaigns/{campaign_id}/resume")
def resume_campaign(campaign_id: str, db: Session = Depends(get_db)):
    campaign = db.get(CustomerReachCampaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, detail={"code": "campaign_not_found", "message": "推广任务不存在"})
    if campaign.status != "paused":
        raise HTTPException(409, detail={"code": "campaign_not_paused", "message": "任务当前未暂停"})
    keep_confirmation = False
    if campaign.current_recipient_id:
        recipient = _campaign_recipient(campaign, campaign.current_recipient_id)
        if recipient and recipient["status"] == "preparing":
            recipient.update(status="pending", step="恢复后重新核对客户")
            flag_modified(campaign, "recipients")
            campaign.current_recipient_id = None
        elif recipient and recipient["status"] == "awaiting_confirmation":
            if campaign.execution_mode == "desktop_preview":
                recipient.update(status="pending", step="恢复后重新核对首位客户", draft_verified=False)
                flag_modified(campaign, "recipients")
                campaign.current_recipient_id = None
            else:
                keep_confirmation = True
    campaign.status = "awaiting_confirmation" if keep_confirmation else "pending"
    campaign.step = "继续当前客户的单独确认" if keep_confirmation else "等待继续处理"
    db.commit()
    if not keep_confirmation:
        _runner.submit(_campaign_work, campaign.id)
    return _campaign_view(campaign)


@router.post("/campaigns/{campaign_id}/skip-current")
def skip_current_recipient(campaign_id: str, body: CampaignConfirmation, db: Session = Depends(get_db)):
    campaign = db.get(CustomerReachCampaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, detail={"code": "campaign_not_found", "message": "推广任务不存在"})
    recipient = _campaign_recipient(campaign, body.recipient_id)
    if body.campaign_id != campaign.id or body.content_fingerprint != campaign.content_fingerprint or not recipient or recipient["customer_key"] != body.customer_key or campaign.current_recipient_id != body.recipient_id:
        raise HTTPException(409, detail={"code": "recipient_changed", "message": "客户或内容与当前推广任务不匹配"})
    if campaign.status != "awaiting_confirmation" or recipient["status"] != "awaiting_confirmation":
        raise HTTPException(409, detail={"code": "recipient_not_skippable", "message": "当前没有等待确认的客户"})
    changed = db.execute(update(CustomerReachCampaign).where(
        CustomerReachCampaign.id == campaign_id,
        CustomerReachCampaign.status == "awaiting_confirmation",
        CustomerReachCampaign.current_recipient_id == body.recipient_id,
    ).values(status="pending", step="用户跳过当前客户，继续队列", current_recipient_id=None))
    if not changed.rowcount:
        db.rollback()
        raise HTTPException(409, detail={"code": "recipient_not_skippable", "message": "当前客户状态已变化"})
    recipient.update(status="skipped", step="用户跳过，未发送", send_result="not_sent",
                     error_reason="用户跳过当前客户", processed_at=datetime.now(timezone.utc).isoformat())
    flag_modified(campaign, "recipients")
    db.commit()
    db.refresh(campaign)
    _runner.submit(_campaign_work, campaign_id)
    return _campaign_view(campaign)


@router.post("/campaigns/{campaign_id}/cancel")
def cancel_campaign(campaign_id: str, db: Session = Depends(get_db)):
    changed = db.execute(update(CustomerReachCampaign).where(CustomerReachCampaign.id == campaign_id,
        CustomerReachCampaign.status.in_(CANCELLABLE)).values(status="cancelled", step="已取消", finished_at=datetime.now(timezone.utc)))
    db.commit()
    if not changed.rowcount:
        raise HTTPException(409, detail={"code": "campaign_not_cancellable", "message": "发送已开始或任务已结束，不能取消"})
    return get_campaign(campaign_id, db)


@router.get("/campaigns/{campaign_id}/screenshot")
def get_campaign_screenshot(campaign_id: str, db: Session = Depends(get_db)):
    campaign = db.get(CustomerReachCampaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, detail={"code": "campaign_not_found", "message": "推广任务不存在"})
    if not campaign.screenshot:
        raise HTTPException(404, detail={"code": "screenshot_unavailable", "message": "当前没有运行时截图"})
    return Response(campaign.screenshot, media_type="image/png")


@router.post("/campaigns/{campaign_id}/recheck-result")
def recheck_single_result(campaign_id: str, db: Session = Depends(get_db)):
    campaign = db.get(CustomerReachCampaign, campaign_id)
    recipient = _campaign_recipient(campaign, campaign.current_recipient_id) if campaign else None
    if not campaign or campaign.execution_mode != "desktop_single" or campaign.status != "unknown" or not recipient or recipient.get("send_attempts") != 1:
        raise HTTPException(409, detail={"code": "result_not_recheckable", "message": "只读复核仅适用于已点击一次的 unknown 单客任务"})
    from app.customer_reach_desktop import DesktopExecutionError, WinAppDesktop
    data = SimpleNamespace(message_text=campaign.message_text, product_url=campaign.product_url)
    evidence = {}
    try:
        WinAppDesktop().verify_single_result(data, dict(recipient), lambda **values: evidence.update(values))
    except DesktopExecutionError as exc:
        raise HTTPException(409, detail={"code": "result_still_unknown", "message": str(exc)}) from exc
    db.refresh(campaign)
    if campaign.status != "unknown":
        raise HTTPException(409, detail={"code": "result_changed", "message": "任务状态已变化"})
    recipient = _campaign_recipient(campaign, campaign.current_recipient_id)
    recipient.update(status="success", send_result="verified", error_reason=None,
                     step="一次点击后只读核验唯一正文与商品卡片原链接通过",
                     processed_at=datetime.now(timezone.utc).isoformat())
    flag_modified(campaign, "recipients")
    campaign.status, campaign.step, campaign.error_reason = "success", "单客发送回显只读复核通过，未重发", None
    campaign.screenshot = evidence["screenshot"]
    campaign.finished_at = datetime.now(timezone.utc)
    db.commit()
    return _campaign_view(campaign)
