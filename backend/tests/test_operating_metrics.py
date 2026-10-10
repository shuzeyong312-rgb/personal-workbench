from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.collection.parser_1688 import CollectionParseError
from app.collection.service import BATCH_RUNTIME, CollectionError, collect_competitor, operating_metrics_status
from app.collection.collector_1688 import OfflineProductDetected
from app.collection.types import CollectionPageResult, OperatingMetricData, ProductData
from app.database import get_db
from app.main import app
from app.models import Base, CollectionRun, Competitor, OperatingMetricObservation, ProductSnapshot


METRIC_KEYS = ("listing_time", "monthly_deal", "monthly_dropship", "annual_units", "annual_orders", "review_count", "positive_rate", "pickup_rate")
STAMP = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)


@pytest.fixture()
def database() -> Generator[tuple[TestClient, sessionmaker[Session], int], None, None]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        competitor = Competitor(
            platform="1688", offer_id="1081895898799", url="https://detail.1688.com/offer/1081895898799.html",
            title="旧标题", shop_name="脱敏店铺", status="active", is_active=True,
            created_at=STAMP, updated_at=STAMP,
        )
        db.add(competitor); db.commit(); competitor_id = competitor.id

    def override_get_db():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        yield client, factory, competitor_id
    finally:
        client.close()
        app.dependency_overrides.clear(); engine.dispose()


def metrics(statuses: list[str], values: list[str | None] | None = None) -> list[OperatingMetricData]:
    values = values or ["20+" if status == "observed" else "-" if status == "placeholder" else None for status in statuses]
    return [OperatingMetricData(key, state, value, "1688_official_procurement_assistant_top", "1081895898799", STAMP, None) for key, state, value in zip(METRIC_KEYS, statuses, values)]


def test_six_value_status_rule_covers_observed_partial_placeholder_and_technical_failures() -> None:
    assert operating_metrics_status(metrics(["observed"] * 8)) == "success"
    assert operating_metrics_status(metrics(["observed", "placeholder", "loading", "source_unavailable", "read_failed", "placeholder", "observed", "observed"])) == "partial"
    assert operating_metrics_status(metrics(["placeholder"] * 8)) == "no_values"
    assert operating_metrics_status(metrics(["read_failed"] * 8)) == "failed"
    assert operating_metrics_status(metrics(["placeholder", "read_failed", "placeholder", "loading", "source_unavailable", "placeholder", "loading", "read_failed"])) == "failed"


def test_base_parse_failure_persists_same_page_metrics_without_a_snapshot(database) -> None:
    _client, factory, competitor_id = database
    candidates = metrics(["observed"] * 4 + ["read_failed"] * 4)
    page_result = CollectionPageResult("1081895898799", None, CollectionParseError("missing base fields"), candidates)
    with factory() as db, patch("app.collection.service.collect_1688_product", return_value=page_result):
        with pytest.raises(CollectionError) as failure:
            collect_competitor(db, competitor_id)
        assert failure.value.operating_metrics_status == "partial"
        run = db.scalar(select(CollectionRun))
        assert run.status == "failed" and run.operating_metrics_status == "partial"
        assert db.scalar(select(func.count()).select_from(ProductSnapshot)) == 0
        observations = db.scalars(select(OperatingMetricObservation).order_by(OperatingMetricObservation.metric_key)).all()
        assert len(observations) == 8
        assert sum(item.status == "observed" for item in observations) == 4


def test_global_offer_mismatch_is_blocked_and_offline_is_not_attempted(database) -> None:
    _client, factory, competitor_id = database
    product = ProductData(
        offer_id="1081895898799", title="脱敏商品", shop_name="脱敏店铺", main_image_url=None,
        price_min=None, price_max=None, product_status="active", collection_source="html",
        captured_at=STAMP, skus=[],
    )
    mismatched = CollectionPageResult("other-offer", product, None, metrics(["observed"] * 8))
    with factory() as db, patch("app.collection.service.collect_1688_product", return_value=mismatched):
        with pytest.raises(CollectionError) as blocked:
            collect_competitor(db, competitor_id)
        assert blocked.value.operating_metrics_status == "blocked"
        run = db.scalar(select(CollectionRun))
        assert run is not None and run.status == "failed" and run.operating_metrics_status == "blocked"
        assert db.scalar(select(func.count()).select_from(OperatingMetricObservation)) == 0
        assert db.scalar(select(func.count()).select_from(ProductSnapshot)) == 0

    with factory() as db, patch("app.collection.service.collect_1688_product", side_effect=OfflineProductDetected()):
        result = collect_competitor(db, competitor_id)
        assert result.operating_metrics_status == "not_attempted"
        assert result.collection_run.status == "success"
        assert db.scalar(select(func.count()).select_from(OperatingMetricObservation)) == 0


def test_metric_write_failure_rolls_back_snapshot_and_observations(database) -> None:
    _client, factory, competitor_id = database
    product = ProductData(
        offer_id="1081895898799", title="脱敏商品", shop_name="脱敏店铺", main_image_url=None,
        price_min=None, price_max=None, product_status="active", collection_source="html",
        captured_at=STAMP, skus=[],
    )
    page_result = CollectionPageResult("1081895898799", product, None, metrics(["observed"] * 8))

    def fail_metric_insert(*_args, **_kwargs) -> None:
        raise RuntimeError("fixture database failure")

    event.listen(OperatingMetricObservation, "before_insert", fail_metric_insert)
    try:
        with factory() as db, patch("app.collection.service.collect_1688_product", return_value=page_result):
            with pytest.raises(CollectionError) as failure:
                collect_competitor(db, competitor_id)
    finally:
        event.remove(OperatingMetricObservation, "before_insert", fail_metric_insert)

    assert failure.value.code == "collection_save_failed"
    with factory() as db:
        run = db.scalar(select(CollectionRun))
        assert run is not None and run.status == "failed" and run.operating_metrics_status == "failed"
        assert db.scalar(select(func.count()).select_from(ProductSnapshot)) == 0
        assert db.scalar(select(func.count()).select_from(OperatingMetricObservation)) == 0


def test_latest_run_failure_does_not_replace_latest_attempt_or_latest_valid(database) -> None:
    client, factory, competitor_id = database
    with factory() as db:
        old = CollectionRun(competitor_id=competitor_id, started_at=STAMP, finished_at=STAMP, status="success", operating_metrics_status="success")
        failed = CollectionRun(competitor_id=competitor_id, started_at=STAMP + timedelta(minutes=1), finished_at=STAMP + timedelta(minutes=2), status="failed", operating_metrics_status="blocked", error_type="offer_id_mismatch", error_message="身份校验失败")
        db.add_all([old, failed]); db.flush()
        db.add_all([
            OperatingMetricObservation(competitor_id=competitor_id, collection_run_id=old.id, platform="1688", offer_id="1081895898799", metric_key="monthly_deal", status="observed", raw_value="20+", source="1688_official_procurement_assistant_top", observed_at=STAMP),
            OperatingMetricObservation(competitor_id=competitor_id, collection_run_id=old.id, platform="1688", offer_id="1081895898799", metric_key="review_count", status="observed", raw_value="4", source="1688_official_procurement_assistant_top", observed_at=STAMP),
        ])
        db.commit(); old_id, failed_id = old.id, failed.id
    response = client.get(f"/api/competitors/{competitor_id}/detail?days=7")
    assert response.status_code == 200
    body = response.json()
    assert body["latest_collection_run"]["id"] == failed_id
    assert body["latest_collection_run"]["operating_metrics_status"] == "blocked"
    deal = next(metric for metric in body["operating_metrics"] if metric["metric_key"] == "monthly_deal")
    assert deal["latest_attempt"]["collection_run_id"] == old_id
    assert deal["latest_valid"]["collection_run_id"] == old_id
    assert deal["latest_valid"]["raw_value"] == "20+"
    assert body["latest_collection_run"]["started_at"].endswith("Z")
    assert deal["latest_attempt"]["observed_at"].endswith("Z")
    assert deal["latest_valid"]["observed_at"].endswith("Z")
    assert next(metric for metric in body["operating_metrics"] if metric["metric_key"] == "pickup_rate")["latest_attempt"] is None
    held = [metric for metric in body["operating_metrics"] if not metric["eligible"]]
    assert held and all(metric["status"] == "not_attempted" and metric["latest_attempt"] is None and metric["latest_valid"] is None for metric in held)


def test_placeholder_attempt_preserves_previous_valid_value_and_source(database) -> None:
    _client, factory, competitor_id = database
    with factory() as db:
        old = CollectionRun(competitor_id=competitor_id, started_at=STAMP, finished_at=STAMP, status="success", operating_metrics_status="success")
        latest = CollectionRun(competitor_id=competitor_id, started_at=STAMP + timedelta(minutes=1), finished_at=STAMP + timedelta(minutes=2), status="success", operating_metrics_status="partial")
        db.add_all([old, latest]); db.flush()
        db.add_all([
            OperatingMetricObservation(competitor_id=competitor_id, collection_run_id=old.id, platform="1688", offer_id="1081895898799", metric_key="monthly_deal", status="observed", raw_value="20+", source="1688_official_procurement_assistant_top", observed_at=STAMP),
            OperatingMetricObservation(competitor_id=competitor_id, collection_run_id=latest.id, platform="1688", offer_id="1081895898799", metric_key="monthly_deal", status="placeholder", raw_value="-", source="1688_official_procurement_assistant_top", observed_at=STAMP + timedelta(minutes=1)),
        ])
        db.commit()
    body = database[0].get(f"/api/competitors/{competitor_id}/detail?days=7").json()
    metric = next(row for row in body["operating_metrics"] if row["metric_key"] == "monthly_deal")
    assert metric["latest_attempt"]["status"] == "placeholder" and metric["latest_attempt"]["raw_value"] == "-"
    assert metric["latest_valid"]["raw_value"] == "20+"
    assert metric["latest_valid"]["collection_run_id"] != metric["latest_attempt"]["collection_run_id"]
