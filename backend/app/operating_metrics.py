from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CollectionRun, OperatingMetricObservation


OPERATING_METRICS = (
    ("listing_time", "上架时间", "经营表现"),
    ("monthly_deal", "月成交", "经营表现"),
    ("monthly_dropship", "月代销", "经营表现"),
    ("annual_units", "年成交件数", "经营表现"),
    ("annual_orders", "年成交笔数", "经营表现"),
    ("review_count", "评论数", "口碑履约"),
    ("positive_rate", "好评率", "口碑履约"),
    ("pickup_rate", "揽收率", "口碑履约"),
)
HELD_OPERATING_METRICS = (
    ("favorite_count", "收藏数", "口碑履约"),
    ("platform_tag_new", "新品", "平台标签"),
    ("platform_tag_popular_new", "人气新品", "平台标签"),
    ("platform_tag_first_release", "首发新品", "平台标签"),
    ("platform_tag_super_new", "超级新品", "平台标签"),
    ("platform_tag_select", "严选", "平台标签"),
    ("platform_tag_cross_border", "跨境", "平台标签"),
    ("platform_tag_store_treasure", "镇店之宝", "平台标签"),
    ("platform_tag_wow_custom", "哇偶定制", "平台标签"),
)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _latest_observations(db: Session, competitor_ids: list[int], *, valid_only: bool) -> dict[tuple[int, str], OperatingMetricObservation]:
    if not competitor_ids:
        return {}
    ranked = select(
        OperatingMetricObservation.id.label("observation_id"),
        OperatingMetricObservation.competitor_id.label("competitor_id"),
        OperatingMetricObservation.metric_key.label("metric_key"),
        func.row_number().over(
            partition_by=(OperatingMetricObservation.competitor_id, OperatingMetricObservation.metric_key),
            order_by=(OperatingMetricObservation.observed_at.desc(), OperatingMetricObservation.id.desc()),
        ).label("row_number"),
    ).where(
        OperatingMetricObservation.competitor_id.in_(competitor_ids),
        *((OperatingMetricObservation.status == "observed", OperatingMetricObservation.raw_value.is_not(None), OperatingMetricObservation.raw_value != "") if valid_only else ()),
    ).subquery()
    rows = db.scalars(
        select(OperatingMetricObservation)
        .join(ranked, ranked.c.observation_id == OperatingMetricObservation.id)
        .where(ranked.c.row_number == 1)
    ).all()
    return {(row.competitor_id, row.metric_key): row for row in rows}


def load_operating_metrics(
    db: Session,
    competitor_ids: list[int],
    *,
    latest_runs: dict[int, CollectionRun | None] | None = None,
) -> dict[int, dict[str, object]]:
    if not competitor_ids:
        return {}
    if latest_runs is None:
        ranked_runs = select(
            CollectionRun.id.label("run_id"),
            CollectionRun.competitor_id.label("competitor_id"),
            func.row_number().over(
                partition_by=CollectionRun.competitor_id,
                order_by=(CollectionRun.started_at.desc(), CollectionRun.id.desc()),
            ).label("row_number"),
        ).where(CollectionRun.competitor_id.in_(competitor_ids)).subquery()
        runs = db.scalars(
            select(CollectionRun).join(ranked_runs, ranked_runs.c.run_id == CollectionRun.id)
            .where(ranked_runs.c.row_number == 1)
        ).all()
        run_by_id = {run.competitor_id: run for run in runs}
    else:
        run_by_id = latest_runs
    attempts = _latest_observations(db, competitor_ids, valid_only=False)
    valid = _latest_observations(db, competitor_ids, valid_only=True)
    result: dict[int, dict[str, object]] = {}
    for competitor_id in competitor_ids:
        run = run_by_id.get(competitor_id)
        result[competitor_id] = {
            "latest_collection_run": ({
                "id": run.id,
                "started_at": _utc(run.started_at),
                "finished_at": _utc(run.finished_at),
                "status": run.status,
                "operating_metrics_status": run.operating_metrics_status,
                "error_type": run.error_type,
                "error_message": run.error_message,
            } if run is not None else None),
            "operating_metrics": [
                {
                    "metric_key": key,
                    "label": label,
                    "section": section,
                    "eligible": True,
                    "status": attempts[(competitor_id, key)].status if (competitor_id, key) in attempts else "not_attempted",
                    "latest_attempt": ({
                        "collection_run_id": attempt.collection_run_id,
                        "status": attempt.status,
                        "raw_value": attempt.raw_value,
                        "source": attempt.source,
                        "observed_at": _utc(attempt.observed_at),
                        "reason": attempt.reason,
                    } if (attempt := attempts.get((competitor_id, key))) is not None else None),
                    "latest_valid": ({
                        "collection_run_id": latest.collection_run_id,
                        "raw_value": latest.raw_value,
                        "source": latest.source,
                        "observed_at": _utc(latest.observed_at),
                    } if (latest := valid.get((competitor_id, key))) is not None else None),
                }
                for key, label, section in OPERATING_METRICS
            ] + [
                {
                    "metric_key": key,
                    "label": label,
                    "section": section,
                    "eligible": False,
                    "status": "not_attempted",
                    "latest_attempt": None,
                    "latest_valid": None,
                }
                for key, label, section in HELD_OPERATING_METRICS
            ],
        }
    return result
