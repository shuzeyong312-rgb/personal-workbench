from datetime import datetime, timedelta, timezone

from app.models import CollectionBatch, CollectionBatchItem, CollectionRun, OperatingMetricObservation
from test_collection_runs import client, add_competitor, add_run


def seed(session):
    start = datetime(2026, 10, 13, 1, tzinfo=timezone.utc)
    for number in range(1, 5):
        product = add_competitor(session, number, title=f"真实商品 {number}", shop_name="可信店铺")
        product.main_image_url = "https://example.test/product.png"
    for number in range(1, 3):
        batch = CollectionBatch(task_id=f"task-{number}", trigger_kind="manual_selected" if number == 1 else "scheduled", created_at=start, started_at=start, finished_at=start + timedelta(minutes=5), lifecycle_status="terminal", outcome_code="partial_success", planned_products=3 if number == 1 else 1, settings_snapshot={})
        session.add(batch)
        session.flush()
        for index in range(3 if number == 1 else 1):
            item = CollectionBatchItem(batch_id=batch.id, competitor_id=index + 1 if number == 1 else 4, position=index, execution_status="completed", final_result=("retry_success", "final_failed", "first_pass_success")[index], base_result="success", attempts_started=2 if index == 0 else 1, page_visits=2 if index == 0 else 1, retry_visits=1 if index == 0 else 0, technical_exception_count=1 if index < 2 else 0)
            session.add(item)
            session.flush()
            for attempt in range(item.attempts_started):
                run = CollectionRun(competitor_id=item.competitor_id, collection_batch_item_id=item.id, attempt_number=attempt + 1, attempt_kind="first_pass" if attempt == 0 else "operating_metrics_retry", started_at=start + timedelta(seconds=attempt * 60), finished_at=start + timedelta(seconds=attempt * 60 + 10), status="success", operating_metrics_status="partial")
                session.add(run)
                session.flush()
                bad = index < 2 and attempt == 0
                session.add(OperatingMetricObservation(competitor_id=item.competitor_id, collection_run_id=run.id, platform="1688", offer_id=f"offer-{item.competitor_id}", metric_key="monthly_deal", status="source_unavailable" if bad else "placeholder", raw_value=None if bad else "-", source="assistant", observed_at=run.started_at, reason="真实来源故障" if bad else None))
    session.commit()


def test_batch_search_filter_and_product_pagination_preserve_history(client):
    api, factory = client
    with factory() as session:
        seed(session)
    assert api.get("/api/collection-batches?search=offer-1").json()["total"] == 1
    assert api.get("/api/collection-batches?search=可信店铺&trigger_kind=manual").json()["total"] == 1
    assert api.get("/api/collection-batches?anomaly=recovered").json()["total"] == 2
    detail = api.get("/api/collection-batches/task-1?anomaly=recovered&attempt_kind=operating_metrics_retry&reason=source_unavailable&page_size=1").json()
    assert detail["total"] == 1
    assert detail["summary"]["planned_products"] == 3
    assert detail["summary"]["succeeded"] == 2
    assert detail["summary"]["anomaly_products"] == 1
    item = detail["items"][0]
    assert item["offer_id"] == "offer-1"
    assert item["main_image_url"] == "https://example.test/product.png"
    assert item["duration_seconds"] == 70
    assert len(item["attempts"]) == 2
    assert item["attempts"][0]["observations"][0]["status"] == "source_unavailable"
    assert item["attempts"][1]["observations"][0]["raw_value"] == "-"
    assert api.get("/api/collection-batches/task-1?search=offer-4").json()["total"] == 0
    current = api.get("/api/collection-batches/task-1?anomaly=current").json()["items"][0]
    assert current["offer_id"] == "offer-2" and current["duration_seconds"] is None
    none = api.get("/api/collection-batches/task-1?anomaly=none").json()
    assert none["total"] == 1 and none["items"][0]["offer_id"] == "offer-3"
    pages = [api.get(f"/api/collection-batches/task-1?page={page}&page_size=1&anomalies_first=true").json()["items"][0]["offer_id"] for page in (1, 2, 3)]
    assert pages == ["offer-2", "offer-1", "offer-3"]
    assert api.get("/api/collection-batches/task-1?page=4&page_size=1").json()["items"] == []


def test_legacy_unknown_filters_single_detail_and_duration_boundaries(client):
    api, factory = client
    start = datetime(2026, 10, 13, tzinfo=timezone.utc)
    with factory() as session:
        add_competitor(session, 1)
        add_run(session, 100, 1, started_at=start, finished_at=start - timedelta(seconds=1))
        add_run(session, 101, 1, started_at=start + timedelta(seconds=60), status="failed")
        session.commit()
    assert api.get("/api/collection-runs?legacy_only=true&anomaly=none").json()["total"] == 0
    assert api.get("/api/collection-runs?legacy_only=true&anomaly=current").json()["total"] == 1
    assert api.get("/api/collection-runs?legacy_only=true&trigger_kind=manual").json()["total"] == 0
    assert api.get("/api/collection-runs?legacy_only=true&trigger_kind=unknown").json()["total"] == 2
    assert api.get("/api/collection-runs?legacy_only=true&started_after=2026-10-13T00:00:30Z").json()["total"] == 1
    detail = api.get("/api/collection-runs/100").json()
    assert detail["collection_batch_item_id"] is None
    assert detail["duration_seconds"] is None
    assert detail["attempt_kind"] is None
    assert detail["observations"] == []
    assert api.get("/api/collection-runs/999").status_code == 404
    assert api.get("/api/collection-batches/nonexistent").status_code == 404


def test_removed_identity_keeps_anonymous_recovery_summary_and_literal_search(client):
    api, factory = client
    with factory() as session:
        seed(session)
        item = session.query(CollectionBatchItem).filter_by(batch_id=2).one()
        for run in session.query(CollectionRun).filter_by(collection_batch_item_id=item.id).all():
            session.query(OperatingMetricObservation).filter_by(collection_run_id=run.id).delete()
            session.delete(run)
        item.competitor_id = None
        session.commit()
    batch_ids = [item["task_id"] for item in api.get("/api/collection-batches?anomaly=recovered").json()["items"]]
    assert "task-2" in batch_ids
    detail = api.get("/api/collection-batches/task-2?anomaly=recovered").json()
    assert detail["total"] == 1
    assert detail["summary"]["succeeded"] == 1
    assert detail["items"][0]["identity_removed"] is True
    assert detail["items"][0]["attempts"] == []
    assert detail["items"][0]["offer_id"] is None
    for value in ("%25", "_"):
        assert api.get(f"/api/collection-batches?search={value}").json()["total"] == 0
        assert api.get(f"/api/collection-batches/task-1?search={value}").json()["total"] == 0
