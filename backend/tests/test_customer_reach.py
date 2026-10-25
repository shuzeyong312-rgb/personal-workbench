import time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import database
from app.database import get_db
from app.main import app
from app.models import Base
from app.models import CustomerReachCampaign
from app import customer_reach_desktop


def test_simulated_task_confirmation_is_bound_and_single_use(monkeypatch):
    database_file = Path(__file__).parent / f"customer-reach-{uuid4()}.db"
    engine = create_engine(f"sqlite:///{database_file.as_posix()}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setenv("PERSONAL_WORKBENCH_DISABLE_SCHEDULER", "1")
    monkeypatch.setenv("PERSONAL_WORKBENCH_CUSTOMER_REACH_MODE", "simulated")

    def test_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = test_db
    previous_factory = getattr(app.state, "collection_session_factory", None)
    app.state.collection_session_factory = lambda: Session(engine)
    try:
        with TestClient(app) as client:
            created = client.post("/api/customer-reach/tasks", json={
                "customer_nickname": "测试买家", "message_text": "新品信息", "product_url": "https://detail.1688.com/offer/123.html",
            })
            assert created.status_code == 201
            task = created.json()
            for _ in range(100):
                task = client.get(f"/api/customer-reach/tasks/{task['id']}").json()
                if task["status"] == "awaiting_confirmation":
                    break
                time.sleep(0.02)
            assert task["status"] == "awaiting_confirmation"
            assert task["matched_customer"] == "测试买家"
            assert task["draft_verified"] is True
            assert client.post("/api/customer-reach/tasks", json={
                "customer_nickname": "另一个买家", "message_text": "新品", "product_url": "https://detail.1688.com/offer/124.html",
            }).status_code == 409

            wrong = client.post(f"/api/customer-reach/tasks/{task['id']}/confirm", json={
                "task_id": task["id"], "customer_nickname": "另一个买家", "content_fingerprint": task["content_fingerprint"],
            })
            assert wrong.status_code == 409
            confirmed = client.post(f"/api/customer-reach/tasks/{task['id']}/confirm", json={
                "task_id": task["id"], "customer_nickname": task["matched_customer"], "content_fingerprint": task["content_fingerprint"],
            })
            assert confirmed.status_code == 200
            assert confirmed.json()["status"] == "sending"
            assert client.post(f"/api/customer-reach/tasks/{task['id']}/cancel").status_code == 409
            assert client.post(f"/api/customer-reach/tasks/{task['id']}/confirm", json={
                "task_id": task["id"], "customer_nickname": task["matched_customer"], "content_fingerprint": task["content_fingerprint"],
            }).status_code == 409
            for _ in range(100):
                task = client.get(f"/api/customer-reach/tasks/{task['id']}").json()
                if task["status"] == "success":
                    break
                time.sleep(0.02)
            assert task["status"] == "success"
            assert task["send_result"] == "simulated"

            created = client.post("/api/customer-reach/tasks", json={
                "customer_nickname": "测试买家", "message_text": "第二条演练", "product_url": "https://detail.1688.com/offer/125.html",
            })
            task_id = created.json()["id"]
            for _ in range(100):
                task = client.get(f"/api/customer-reach/tasks/{task_id}").json()
                if task["status"] == "awaiting_confirmation":
                    break
                time.sleep(0.02)
            assert client.post(f"/api/customer-reach/tasks/{task_id}/pause").json()["status"] == "paused"
            resumed = client.post(f"/api/customer-reach/tasks/{task_id}/resume")
            assert resumed.json()["status"] == "awaiting_confirmation"
            assert client.post(f"/api/customer-reach/tasks/{task_id}/cancel").json()["status"] == "cancelled"

            paused = client.post("/api/customer-reach/tasks", json={
                "customer_nickname": "测试买家", "message_text": "暂停后取消", "product_url": "https://detail.1688.com/offer/127.html",
            }).json()
            for _ in range(100):
                paused = client.get(f"/api/customer-reach/tasks/{paused['id']}").json()
                if paused["status"] == "awaiting_confirmation":
                    break
                time.sleep(0.02)
            assert client.post(f"/api/customer-reach/tasks/{paused['id']}/pause").json()["status"] == "paused"
            assert client.post(f"/api/customer-reach/tasks/{paused['id']}/cancel").json()["status"] == "cancelled"

            monkeypatch.setenv("PERSONAL_WORKBENCH_CUSTOMER_REACH_MODE", "desktop")

            def prepare_without_desktop(self, task, update):
                update(status="awaiting_confirmation", step="测试待确认", matched_customer=task.customer_nickname, draft_verified=True)

            def uncertain_send(self, task, update):
                raise customer_reach_desktop.DesktopExecutionError("回显不确定", may_have_sent=True)

            monkeypatch.setattr(customer_reach_desktop.WinAppDesktop, "prepare", prepare_without_desktop)
            monkeypatch.setattr(customer_reach_desktop.WinAppDesktop, "send", uncertain_send)
            created = client.post("/api/customer-reach/tasks", json={
                "customer_nickname": "测试买家", "message_text": "未知结果演练", "product_url": "https://detail.1688.com/offer/126.html",
            })
            task_id = created.json()["id"]
            for _ in range(100):
                task = client.get(f"/api/customer-reach/tasks/{task_id}").json()
                if task["status"] == "awaiting_confirmation":
                    break
                time.sleep(0.02)
            payload = {"task_id": task_id, "customer_nickname": task["matched_customer"], "content_fingerprint": task["content_fingerprint"]}
            assert client.post(f"/api/customer-reach/tasks/{task_id}/confirm", json=payload).status_code == 200
            for _ in range(100):
                task = client.get(f"/api/customer-reach/tasks/{task_id}").json()
                if task["status"] == "unknown":
                    break
                time.sleep(0.02)
            assert task["status"] == "unknown"
            assert task["send_result"] == "unknown"
            assert client.post(f"/api/customer-reach/tasks/{task_id}/confirm", json=payload).status_code == 409
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.state.collection_session_factory = previous_factory
        engine.dispose()
        database_file.unlink(missing_ok=True)


def test_simulated_campaign_confirms_each_recipient_and_resumes_without_repeating_success(monkeypatch):
    database_file = Path(__file__).parent / f"customer-reach-campaign-{uuid4()}.db"
    engine = create_engine(f"sqlite:///{database_file.as_posix()}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setenv("PERSONAL_WORKBENCH_DISABLE_SCHEDULER", "1")
    monkeypatch.setenv("PERSONAL_WORKBENCH_CUSTOMER_REACH_MODE", "simulated")

    def test_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = test_db
    previous_factory = getattr(app.state, "collection_session_factory", None)
    app.state.collection_session_factory = lambda: Session(engine)
    try:
        with TestClient(app) as client:
            created = client.post("/api/customer-reach/campaigns", json={
                "customer_category": "inquiry", "message_text": "新品演练文案",
                "product_url": "https://detail.1688.com/offer/991.html",
            })
            assert created.status_code == 201
            campaign_id = created.json()["id"]

            def wait_for(predicate):
                result = None
                for _ in range(150):
                    result = client.get(f"/api/customer-reach/campaigns/{campaign_id}").json()
                    if predicate(result):
                        return result
                    time.sleep(0.02)
                raise AssertionError(f"campaign state timed out: {result}")

            campaign = wait_for(lambda item: item["status"] == "awaiting_confirmation")
            first, skipped = campaign["recipients"][0], campaign["recipients"][2]
            assert campaign["current_recipient_id"] == first["recipient_id"]
            assert first["status"] == "awaiting_confirmation" and first["draft_verified"] is True
            assert first["matched_customer"] == first["nickname"]
            assert first["nickname"] == "模拟客户 1"
            assert skipped["status"] == "skipped" and not skipped["eligible"]
            assert client.post(f"/api/customer-reach/campaigns/{campaign_id}/confirm", json={
                "campaign_id": campaign_id, "recipient_id": first["recipient_id"], "customer_key": "wrong",
                "content_fingerprint": campaign["content_fingerprint"],
            }).status_code == 409

            payload = {"campaign_id": campaign_id, "recipient_id": first["recipient_id"],
                       "customer_key": first["customer_key"], "content_fingerprint": campaign["content_fingerprint"]}
            confirmed = client.post(f"/api/customer-reach/campaigns/{campaign_id}/confirm", json=payload)
            assert confirmed.status_code == 200, confirmed.json()
            campaign = wait_for(lambda item: item["status"] == "awaiting_confirmation")
            second = campaign["recipients"][1]
            assert campaign["recipients"][0]["status"] == "success"
            assert campaign["current_recipient_id"] == second["recipient_id"]

            assert client.post(f"/api/customer-reach/campaigns/{campaign_id}/pause").json()["status"] == "paused"
            assert client.post(f"/api/customer-reach/campaigns/{campaign_id}/resume").json()["status"] == "awaiting_confirmation"
            campaign = wait_for(lambda item: item["status"] == "awaiting_confirmation")
            assert campaign["recipients"][0]["status"] == "success"
            second = next(row for row in campaign["recipients"] if row["recipient_id"] == campaign["current_recipient_id"])
            payload = {"campaign_id": campaign_id, "recipient_id": second["recipient_id"],
                       "customer_key": second["customer_key"], "content_fingerprint": campaign["content_fingerprint"]}
            assert client.post(f"/api/customer-reach/campaigns/{campaign_id}/confirm", json=payload).status_code == 200
            campaign = wait_for(lambda item: item["status"] == "success")
            assert [row["status"] for row in campaign["recipients"]] == ["success", "success", "skipped"]
            assert client.post(f"/api/customer-reach/campaigns/{campaign_id}/confirm", json=payload).status_code == 409
            with Session(engine) as db:
                stored = db.get(CustomerReachCampaign, campaign_id)
                assert stored.recipients[0]["send_result"] == "simulated"
                assert stored.recipients[1]["send_result"] == "simulated"

            skipped_campaign = client.post("/api/customer-reach/campaigns", json={
                "customer_category": "inquiry", "message_text": "跳过演练文案",
                "product_url": "https://detail.1688.com/offer/992.html",
            }).json()
            campaign_id = skipped_campaign["id"]
            first_campaign = wait_for(lambda item: item["status"] == "awaiting_confirmation")
            first_recipient = next(row for row in first_campaign["recipients"] if row["recipient_id"] == first_campaign["current_recipient_id"])
            skip_payload = {"campaign_id": campaign_id, "recipient_id": first_recipient["recipient_id"],
                            "customer_key": first_recipient["customer_key"], "content_fingerprint": first_campaign["content_fingerprint"]}
            skipped_response = client.post(f"/api/customer-reach/campaigns/{campaign_id}/skip-current", json=skip_payload)
            assert skipped_response.status_code == 200
            next_customer = wait_for(lambda item: item["status"] == "awaiting_confirmation")
            assert next_customer["recipients"][0]["status"] == "skipped"
            assert next_customer["recipients"][0]["send_result"] == "not_sent"
            assert next_customer["recipients"][0]["recipient_id"] == first_recipient["recipient_id"]
            assert next_customer["recipients"][1]["status"] == "awaiting_confirmation"
            assert client.post(f"/api/customer-reach/campaigns/{campaign_id}/skip-current", json=skip_payload).status_code == 409
            assert client.get(f"/api/customer-reach/campaigns/{campaign_id}").json()["recipients"][1]["status"] == "awaiting_confirmation"
            assert client.post(f"/api/customer-reach/campaigns/{campaign_id}/cancel").status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.state.collection_session_factory = previous_factory
        engine.dispose()
        database_file.unlink(missing_ok=True)
