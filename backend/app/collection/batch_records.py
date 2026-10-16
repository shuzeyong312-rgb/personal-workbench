from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import String, and_, case, func, or_, select
from sqlalchemy.orm import Session

from fastapi import HTTPException

from app.models import CollectionAddInput, CollectionBatch, CollectionBatchItem, CollectionRun, Competitor, OperatingMetricObservation


Anomaly = Literal["current", "none", "recovered", "all", "placeholder", "source_unavailable", "loading", "read_failed", "base_failed", "rejected", "verification_required"]
_ANOMALY_STATUS = {
    "placeholder": "placeholder",
    "source_unavailable": "source_unavailable",
    "loading": "loading",
    "read_failed": "read_failed",
}


SUCCESS_RESULTS = {"first_pass_success", "verification_resume_success", "retry_success"}
TECHNICAL_STATUSES = {"source_unavailable", "loading", "read_failed"}


def duration_seconds(start: datetime | None, finish: datetime | None) -> float | None:
    if start is None or finish is None:
        return None
    start = start.replace(tzinfo=timezone.utc) if start.tzinfo is None else start
    finish = finish.replace(tzinfo=timezone.utc) if finish.tzinfo is None else finish
    return (finish - start).total_seconds() if finish >= start else None


def current_anomaly():
    return or_(CollectionBatchItem.final_result.in_(["final_failed", "verification_required"]), CollectionBatchItem.base_result == "failed", (CollectionBatchItem.final_result.is_(None) & (CollectionBatchItem.technical_exception_count > 0)))


def historical_anomaly():
    history = select(CollectionRun.id).outerjoin(OperatingMetricObservation, OperatingMetricObservation.collection_run_id == CollectionRun.id).where(CollectionRun.collection_batch_item_id == CollectionBatchItem.id, or_(CollectionRun.status == "failed", OperatingMetricObservation.status.in_(TECHNICAL_STATUSES))).exists()
    return or_(history, CollectionBatchItem.technical_exception_count > 0,
               CollectionBatchItem.source_unavailable_count > 0, CollectionBatchItem.loading_count > 0,
               CollectionBatchItem.read_failed_count > 0)


def list_collection_runs(
    db: Session, *, search: str | None, status: str, ownership: str,
    batch_id: str | None, anomaly: str, legacy_only: bool, page: int, page_size: int,
    started_after: datetime | None = None, started_before: datetime | None = None, trigger_kind: str = "all",
) -> dict[str, object]:
    filters = []
    if started_after is not None:
        filters.append(CollectionRun.started_at >= started_after)
    if started_before is not None:
        filters.append(CollectionRun.started_at <= started_before)
    if trigger_kind != "all":
        filters.append(CollectionRun.collection_batch_item_id.is_(None) if trigger_kind == "unknown" else CollectionBatch.trigger_kind.in_(["manual_selected", "manual_all_active", "manual_single"]) if trigger_kind == "manual" else CollectionBatch.trigger_kind == trigger_kind)
    if status != "all":
        filters.append(CollectionRun.status == status)
    if ownership != "all":
        filters.append(Competitor.ownership == ownership)
    query = search.strip().lower() if search else ""
    if query:
        pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        filters.append(or_(
            func.cast(CollectionRun.id, String).like(pattern, escape="\\"),
            func.lower(Competitor.title).like(pattern, escape="\\"),
            func.lower(Competitor.offer_id).like(pattern, escape="\\"),
            func.lower(Competitor.shop_name).like(pattern, escape="\\"),
        ))
    if batch_id:
        filters.append(CollectionBatch.task_id == batch_id)
    if anomaly == "base_failed":
        filters.append(CollectionRun.status == "failed")
    elif anomaly in {"current", "none", "recovered"}:
        technical = select(OperatingMetricObservation.id).where(OperatingMetricObservation.collection_run_id == CollectionRun.id, OperatingMetricObservation.status.in_(TECHNICAL_STATUSES)).exists()
        current = or_(CollectionRun.status == "failed", technical)
        known = select(OperatingMetricObservation.id).where(OperatingMetricObservation.collection_run_id == CollectionRun.id).exists()
        add_run_without_anomaly = and_(CollectionBatch.trigger_kind == "add_links", CollectionRun.status == "success", ~current)
        filters.append(current if anomaly == "current" else or_(and_(~current, known), add_run_without_anomaly) if anomaly == "none" else CollectionRun.id < 0)
    elif anomaly != "all":
        filters.append(OperatingMetricObservation.status == anomaly)
    base = (select(CollectionRun, Competitor, CollectionBatch)
            .join(Competitor, Competitor.id == CollectionRun.competitor_id)
            .outerjoin(CollectionBatchItem, CollectionBatchItem.id == CollectionRun.collection_batch_item_id)
            .outerjoin(CollectionBatch, CollectionBatch.id == CollectionBatchItem.batch_id)
            .distinct())
    if anomaly in _ANOMALY_STATUS:
        base = base.join(OperatingMetricObservation, OperatingMetricObservation.collection_run_id == CollectionRun.id)
    if filters:
        base = base.where(*filters)
    if legacy_only:
        base = base.where(CollectionRun.collection_batch_item_id.is_(None))
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(
        base.order_by(CollectionRun.started_at.desc(), CollectionRun.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    run_ids = [run.id for run, _, _ in rows]
    observation_states: dict[int, set[str]] = {}
    if run_ids:
        for run_id, field_status in db.execute(select(OperatingMetricObservation.collection_run_id, OperatingMetricObservation.status).where(OperatingMetricObservation.collection_run_id.in_(run_ids))):
            observation_states.setdefault(run_id, set()).add(field_status)
    return {
        "items": [{
            "id": run.id, "competitor_id": run.competitor_id,
            "ownership": competitor.ownership, "title": competitor.title,
            "offer_id": competitor.offer_id, "shop_name": competitor.shop_name,
            "started_at": run.started_at, "finished_at": run.finished_at,
            "status": run.status, "operating_metrics_status": run.operating_metrics_status,
            "error_type": run.error_type, "error_message": run.error_message,
            "has_anomaly": True if run.status == "failed" or observation_states.get(run.id, set()) & TECHNICAL_STATUSES else False if observation_states.get(run.id) else None,
            "duration_seconds": max(0.0, (run.finished_at - run.started_at).total_seconds()) if run.finished_at else None,
            "collection_batch_item_id": run.collection_batch_item_id,
            "attempt_number": run.attempt_number, "attempt_kind": run.attempt_kind,
            "batch_id": batch.task_id if batch else None,
        } for run, competitor, batch in rows],
        "total": total, "page": page, "page_size": page_size,
    }


def list_batches(
    db: Session, *, page: int, page_size: int,
    trigger_kind: str, outcome: str, anomaly: Anomaly,
    started_after: datetime | None, started_before: datetime | None, search: str | None = None,
) -> dict[str, object]:
    filters = []
    if trigger_kind != "all":
        filters.append(CollectionBatch.trigger_kind.in_(["manual_selected", "manual_all_active", "manual_single"]) if trigger_kind == "manual" else CollectionBatch.trigger_kind == trigger_kind)
    if search and search.strip():
        pattern = "%" + search.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        product_match = select(CollectionBatchItem.id).join(Competitor, Competitor.id == CollectionBatchItem.competitor_id).where(CollectionBatchItem.batch_id == CollectionBatch.id, or_(func.lower(Competitor.title).like(pattern, escape="\\"), func.lower(Competitor.shop_name).like(pattern, escape="\\"), func.lower(Competitor.offer_id).like(pattern, escape="\\"))).exists()
        filters.append(or_(func.lower(CollectionBatch.task_id).like(pattern, escape="\\"), product_match))
    from app.collection.add_links import REJECTED
    add_mode = CollectionBatch.trigger_kind == "add_links"
    def add_has(codes):
        return select(CollectionAddInput.id).where(CollectionAddInput.batch_id == CollectionBatch.id, CollectionAddInput.result_code.in_(codes)).exists()
    add_metric_anomaly = or_(
        select(CollectionRun.id).join(OperatingMetricObservation, OperatingMetricObservation.collection_run_id == CollectionRun.id).where(
            CollectionRun.collection_batch_item_id == CollectionBatchItem.id, OperatingMetricObservation.status.in_(TECHNICAL_STATUSES)
        ).exists(),
        and_(CollectionBatchItem.identity_state == 'removed', CollectionBatchItem.technical_exception_count > 0),
    )
    add_metric_current = select(CollectionBatchItem.id).where(CollectionBatchItem.batch_id == CollectionBatch.id, add_metric_anomaly).exists()
    add_current = or_(add_has(["technical_failed", "verification_required", "interrupted"]), add_metric_current, CollectionBatch.outcome_code.in_(["infrastructure_error", "interrupted"]))
    add_none = and_(CollectionBatch.lifecycle_status == "terminal", ~add_current, ~add_has(["not_executed"]), ~select(CollectionAddInput.id).where(CollectionAddInput.batch_id == CollectionBatch.id, CollectionAddInput.result_code.is_(None)).exists())
    if trigger_kind != "unknown" and ((trigger_kind == "add_links" and anomaly == "recovered") or (trigger_kind not in {"all", "add_links"} and anomaly == "rejected")):
        raise HTTPException(422, {"code": "incompatible_filter", "allowed_anomalies": ["all", "current", "none", "base_failed", "rejected", "verification_required", "placeholder", "source_unavailable", "loading", "read_failed"] if trigger_kind == "add_links" else ["all", "current", "none", "recovered", "placeholder", "source_unavailable", "loading", "read_failed", "base_failed", "verification_required"]})
    if anomaly in {"current", "none", "recovered"}:
        current = select(CollectionBatchItem.id).where(CollectionBatchItem.batch_id == CollectionBatch.id, current_anomaly()).exists()
        recovered = select(CollectionBatchItem.id).where(CollectionBatchItem.batch_id == CollectionBatch.id, CollectionBatchItem.final_result.in_(SUCCESS_RESULTS), historical_anomaly()).exists()
        incomplete = select(CollectionBatchItem.id).where(CollectionBatchItem.batch_id == CollectionBatch.id, or_(CollectionBatchItem.final_result.is_(None), CollectionBatchItem.final_result == "not_executed")).exists()
        normal_none = and_(CollectionBatch.lifecycle_status == "terminal", CollectionBatch.outcome_code.notin_(["infrastructure_error", "interrupted"]), ~current, ~incomplete)
        normal = current if anomaly == "current" else normal_none if anomaly == "none" else recovered
        filters.append(or_(and_(~add_mode, normal), and_(add_mode, add_current if anomaly == "current" else add_none if anomaly == "none" else False)))
    if anomaly == "rejected":
        filters.append(and_(add_mode, add_has(REJECTED)))
    if anomaly == "verification_required":
        normal = select(CollectionBatchItem.id).where(CollectionBatchItem.batch_id == CollectionBatch.id, CollectionBatchItem.final_result == "verification_required").exists()
        filters.append(or_(and_(add_mode, add_has(["verification_required"])), and_(~add_mode, normal)))
    if outcome != "all":
        filters.append(CollectionBatch.outcome_code == outcome)
    if started_after is not None:
        filters.append(CollectionBatch.started_at >= started_after)
    if started_before is not None:
        filters.append(CollectionBatch.started_at <= started_before)
    if anomaly == "base_failed":
        filters.append(select(CollectionBatchItem.batch_id).where(
            CollectionBatchItem.batch_id == CollectionBatch.id,
            CollectionBatchItem.base_result == "failed",
        ).exists())
    elif anomaly in _ANOMALY_STATUS:
        snapshot_column = {
            "placeholder": CollectionBatchItem.placeholder_count,
            "source_unavailable": CollectionBatchItem.source_unavailable_count,
            "loading": CollectionBatchItem.loading_count,
            "read_failed": CollectionBatchItem.read_failed_count,
        }[anomaly]
        matching_batch = (
            select(CollectionBatchItem.batch_id)
            .join(CollectionRun, CollectionRun.collection_batch_item_id == CollectionBatchItem.id)
            .join(OperatingMetricObservation, OperatingMetricObservation.collection_run_id == CollectionRun.id)
            .where(CollectionBatchItem.batch_id == CollectionBatch.id, OperatingMetricObservation.status == _ANOMALY_STATUS[anomaly])
            .exists()
        )
        filters.append(or_(matching_batch, select(CollectionBatchItem.id).where(
            CollectionBatchItem.batch_id == CollectionBatch.id,
            snapshot_column > 0,
        ).exists()))
    base = select(CollectionBatch).where(*filters)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    batches = db.scalars(
        base.order_by(CollectionBatch.started_at.desc(), CollectionBatch.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    batch_ids = [batch.id for batch in batches]
    summaries: dict[int, dict[str, int]] = {batch_id: {} for batch_id in batch_ids}
    aggregates: dict[int, tuple[int, int, int, int, int, int, int, int]] = {}
    if batch_ids:
        for batch_id, final_result, count in db.execute(
            select(CollectionBatchItem.batch_id, CollectionBatchItem.final_result, func.count())
            .where(CollectionBatchItem.batch_id.in_(batch_ids))
            .group_by(CollectionBatchItem.batch_id, CollectionBatchItem.final_result)
        ):
            summaries[batch_id][final_result or "pending"] = count
        aggregates = {
            row[0]: tuple(value or 0 for value in row[1:])
            for row in db.execute(select(
                CollectionBatchItem.batch_id,
                func.sum(CollectionBatchItem.attempts_started),
                func.sum(CollectionBatchItem.verification_resume_visits),
                func.sum(CollectionBatchItem.technical_exception_count),
                func.sum(case((CollectionBatchItem.base_result == "failed", 1), else_=0)),
                func.sum(case((CollectionBatchItem.final_result.is_not(None) & (CollectionBatchItem.final_result != "not_executed"), 1), else_=0)),
                func.sum(CollectionBatchItem.page_visits_unknown),
                func.sum(case((CollectionBatchItem.final_result == "verification_required", 1), else_=0)),
                func.sum(case((
                    (CollectionBatchItem.final_result == "final_failed") & (CollectionBatchItem.technical_exception_count > 0), 1
                ), else_=0)),
            ).where(CollectionBatchItem.batch_id.in_(batch_ids)).group_by(CollectionBatchItem.batch_id))
        }
    visit_summaries = {}
    if batch_ids:
        visit_summaries = {
            batch_id: (visits or 0, unknown or 0, retries or 0)
            for batch_id, visits, unknown, retries in db.execute(
                select(
                    CollectionBatchItem.batch_id,
                    func.sum(CollectionBatchItem.page_visits),
                    func.sum(CollectionBatchItem.page_visits_unknown),
                    func.sum(CollectionBatchItem.retry_visits),
                ).where(CollectionBatchItem.batch_id.in_(batch_ids)).group_by(CollectionBatchItem.batch_id)
            )
        }
    exception_summaries = {}
    if batch_ids:
        exception_summaries = {
            batch_id: tuple(value or 0 for value in counts)
            for batch_id, *counts in db.execute(select(
                CollectionBatchItem.batch_id,
                func.sum(CollectionBatchItem.placeholder_count),
                func.sum(CollectionBatchItem.source_unavailable_count),
                func.sum(CollectionBatchItem.loading_count),
                func.sum(CollectionBatchItem.read_failed_count),
            ).where(CollectionBatchItem.batch_id.in_(batch_ids)).group_by(CollectionBatchItem.batch_id))
        }
    from app.collection.add_links import input_summary
    add_inputs = {}
    if batch_ids:
        for row in db.scalars(select(CollectionAddInput).where(CollectionAddInput.batch_id.in_(batch_ids))):
            add_inputs.setdefault(row.batch_id, []).append(row)
    add_metric_items: dict[int, set[int]] = {}
    if batch_ids:
        for batch_id, item_id in db.execute(select(CollectionBatchItem.batch_id, CollectionBatchItem.id).where(
            CollectionBatchItem.batch_id.in_(batch_ids), add_metric_anomaly
        )):
            add_metric_items.setdefault(batch_id, set()).add(item_id)
    items = []
    for batch in batches:
        summary = summaries[batch.id]
        totals = aggregates.get(batch.id, (0,) * 8)
        exceptions = exception_summaries.get(batch.id, (0,) * 4)
        items.append({
            "batch_id": batch.id, "task_id": batch.task_id,
            "trigger_kind": batch.trigger_kind, "created_at": batch.created_at,
            "duration_seconds": duration_seconds(batch.started_at, batch.finished_at),
            "started_at": batch.started_at, "finished_at": batch.finished_at,
            "lifecycle_status": batch.lifecycle_status,
            "outcome_code": batch.outcome_code,
            "batch_outcome_code": batch.outcome_code,
            "planned_products": batch.planned_products,
            "completed": totals[4], "remaining": batch.planned_products - totals[4],
            "attempts_started": totals[0], "counts": summary,
            "page_visits": visit_summaries.get(batch.id, (0, 0, 0))[0],
            "page_visits_unknown": totals[5],
            "verification_resume_visits": totals[1],
            "retry_visits": visit_summaries.get(batch.id, (0, 0, 0))[2],
            "circuit_breaker_cancelled": batch.circuit_breaker_cancelled,
            "first_pass_success": summary.get("first_pass_success", 0),
            "verification_resume_success": summary.get("verification_resume_success", 0),
            "retry_success": summary.get("retry_success", 0),
            "succeeded": sum(summary.get(key, 0) for key in SUCCESS_RESULTS),
            "anomaly_products": summary.get("final_failed", 0) + summary.get("verification_required", 0),
            "final_failed": summary.get("final_failed", 0),
            "verification_required": totals[6],
            "technical_exception_products": totals[7],
            "base_failed_products": totals[3],
            "not_executed": summary.get("not_executed", 0),
            "retry_max": int(batch.settings_snapshot.get("operating_metrics_retry_max", 0)),
            "exception_types": [name for name, count in (
                ("placeholder", exceptions[0]),
                ("source_unavailable", exceptions[1]),
                ("loading", exceptions[2]),
                ("read_failed", exceptions[3]),
                ("base_failed", totals[3]),
            ) if count],
        })
    for value, batch in zip(items, batches):
        value["task_kind"] = "add_links" if batch.trigger_kind == "add_links" else "collect_products"
        if batch.trigger_kind == "add_links":
            summary = input_summary(add_inputs.get(batch.id, []), batch.planned_products)
            value["input_summary"] = summary
            metric_item_ids = add_metric_items.get(batch.id, set())
            anomalous_rows = {row.id for row in add_inputs.get(batch.id, []) if row.result_code in {"technical_failed", "verification_required", "interrupted"} or row.batch_item_id in metric_item_ids}
            value["technical_exception_products"] = len(metric_item_ids)
            value["anomaly_products"] = len(anomalous_rows)
            value["base_failed_products"] = summary["technical_failed"]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def get_batch(db: Session, task_id: str, *, search: str | None = None, final_result: str = "all", anomaly: str = "all", attempt_kind: str = "all", reason: str = "all", anomalies_first: bool = False, page: int = 1, page_size: int | None = None, input_result: str = "all") -> dict[str, object] | None:
    batch = db.scalar(select(CollectionBatch).where(CollectionBatch.task_id == task_id))
    if batch is None:
        return None
    if batch.trigger_kind == "add_links":
        from app.collection.add_links import add_task_detail
        return add_task_detail(db, batch, search=search, final_result=final_result, anomaly=anomaly, input_result=input_result, attempt_kind=attempt_kind, reason=reason, anomalies_first=anomalies_first, page=page, page_size=page_size)
    if input_result != "all":
        raise HTTPException(422, {"code": "incompatible_filter"})
    rows = db.execute(
        select(CollectionBatchItem, Competitor)
        .outerjoin(Competitor, Competitor.id == CollectionBatchItem.competitor_id)
        .where(CollectionBatchItem.batch_id == batch.id)
        .order_by(CollectionBatchItem.position)
    ).all()
    item_ids = [item.id for item, _ in rows]
    runs_by_item: dict[int, list[dict[str, object]]] = {item_id: [] for item_id in item_ids}
    if item_ids:
        run_rows = db.execute(
            select(CollectionRun, OperatingMetricObservation)
            .outerjoin(OperatingMetricObservation, OperatingMetricObservation.collection_run_id == CollectionRun.id)
            .where(CollectionRun.collection_batch_item_id.in_(item_ids))
            .order_by(CollectionRun.collection_batch_item_id, CollectionRun.attempt_number, OperatingMetricObservation.metric_key)
        ).all()
        runs: dict[int, dict[str, object]] = {}
        for run, observation in run_rows:
            value = runs.setdefault(run.id, {
                "item_id": run.collection_batch_item_id,
                "id": run.id, "attempt_number": run.attempt_number, "attempt_kind": run.attempt_kind,
                "started_at": run.started_at, "finished_at": run.finished_at, "status": run.status,
                "operating_metrics_status": run.operating_metrics_status, "error_type": run.error_type,
                "error_message": run.error_message, "navigation_claimed_at": run.navigation_claimed_at,
                "navigation_confirmed_at": run.navigation_confirmed_at, "navigation_terminal_reason": run.navigation_terminal_reason,
                "duration_seconds": duration_seconds(run.started_at, run.finished_at),
                "observations": [],
            })
            if observation is not None:
                value["observations"].append({
                    "metric_key": observation.metric_key, "status": observation.status,
                    "raw_value": observation.raw_value, "reason": observation.reason,
                    "source": observation.source, "observed_at": observation.observed_at,
                })
        for run in runs.values():
            item_id = run.pop("item_id")
            runs_by_item[item_id].append(run)
    result = {
        "batch_id": batch.id, "task_id": batch.task_id, "trigger_kind": batch.trigger_kind,
        "created_at": batch.created_at, "started_at": batch.started_at,
        "finished_at": batch.finished_at, "lifecycle_status": batch.lifecycle_status,
        "outcome_code": batch.outcome_code, "batch_outcome_code": batch.outcome_code,
        "settings_snapshot": batch.settings_snapshot, "planned_products": batch.planned_products,
        "protection_reason": batch.protection_reason, "protection_details": batch.protection_details,
        "circuit_breaker_streak": batch.circuit_breaker_streak,
        "circuit_breaker_cancelled": batch.circuit_breaker_cancelled,
        "items": [{
            "position": item.position, "competitor_id": item.competitor_id,
            "title": competitor.title if competitor else None,
            "shop_name": competitor.shop_name if competitor else None,
            "offer_id": competitor.offer_id if competitor else None,
            "main_image_url": competitor.main_image_url if competitor else None,
            "execution_status": item.execution_status, "final_result": item.final_result,
            "base_result": item.base_result, "base_status": item.base_result,
            "operating_metrics_status": item.operating_metrics_status,
            "attempts_started": item.attempts_started, "page_visits": item.page_visits,
            "page_visits_unknown": item.page_visits_unknown,
            "verification_resume_visits": item.verification_resume_visits,
            "retry_visits": item.retry_visits, "technical_exception_count": item.technical_exception_count,
            "placeholder_count": item.placeholder_count,
            "source_unavailable_count": item.source_unavailable_count,
            "loading_count": item.loading_count, "read_failed_count": item.read_failed_count,
            "cancelled_retry_count": item.cancelled_retry_count,
            "protection_reason": item.protection_reason, "stop_reason": item.stop_reason,
            "attempts": runs_by_item[item.id],
            "identity_state": item.identity_state,
            "identity_removed": item.identity_state == "removed",
            "deletion_notice": "商品已删除，字段明细已随商品删除" if item.competitor_id is None else None,
        } for item, competitor in rows],
    }

    items = result["items"]
    for item in items:
        attempts = item["attempts"]
        item["has_anomaly"] = item["final_result"] in {"final_failed", "verification_required"} or item["base_result"] == "failed" or (item["final_result"] is None and item["technical_exception_count"] > 0)
        item["had_anomaly"] = bool(item["technical_exception_count"] or item["source_unavailable_count"] or item["loading_count"] or item["read_failed_count"]) or any(attempt["status"] == "failed" or any(observation["status"] in TECHNICAL_STATUSES for observation in attempt["observations"]) for attempt in attempts)
        item["started_at"] = min((attempt["started_at"] for attempt in attempts), default=None)
        item["last_attempt_finished_at"] = max((attempt["finished_at"] for attempt in attempts if attempt["finished_at"]), default=None)
        # Failed items may only be finalized when the retry queue closes; no item timestamp is persisted.
        item["finished_at"] = item["last_attempt_finished_at"] if item["final_result"] in SUCCESS_RESULTS and all(attempt["finished_at"] for attempt in attempts) else None
        item["duration_seconds"] = duration_seconds(item["started_at"], item["finished_at"])
    counts = {}
    for item in items:
        key = item["final_result"] or "pending"
        counts[key] = counts.get(key, 0) + 1
    result["summary"] = {
        "planned_products": batch.planned_products, "counts": counts,
        **{key: sum(item[key] for item in items) for key in ("page_visits", "page_visits_unknown", "retry_visits", "verification_resume_visits")},
        "duration_seconds": duration_seconds(batch.started_at, batch.finished_at),
        "succeeded": sum(counts.get(key, 0) for key in SUCCESS_RESULTS),
        "anomaly_products": sum(bool(item["has_anomaly"]) for item in items),
        "completed": sum(count for key, count in counts.items() if key not in {"pending", "not_executed"}),
        "remaining": batch.planned_products - sum(count for key, count in counts.items() if key not in {"pending", "not_executed"}),
    }
    query = search.strip().lower() if search else ""
    def matches(item):
        if query and not any(query in str(item.get(key) or "").lower() for key in ("title", "shop_name", "offer_id")):
            return False
        if final_result == "success" and item["final_result"] not in SUCCESS_RESULTS:
            return False
        if final_result == "exception" and not item["has_anomaly"]:
            return False
        if final_result == "pending" and item["final_result"] is not None:
            return False
        if final_result not in {"all", "success", "exception", "pending"} and item["final_result"] != final_result:
            return False
        if anomaly == "base_failed" and item["base_result"] != "failed":
            return False
        if anomaly == "verification_required" and item["final_result"] != "verification_required":
            return False
        if anomaly == "current" and not item["has_anomaly"]:
            return False
        if anomaly == "recovered" and not (item["had_anomaly"] and item["final_result"] in SUCCESS_RESULTS and not item["has_anomaly"]):
            return False
        if anomaly == "none" and (item["has_anomaly"] or item["had_anomaly"] or item["final_result"] not in SUCCESS_RESULTS):
            return False
        if attempt_kind != "all" and not any(attempt["attempt_kind"] == attempt_kind for attempt in item["attempts"]):
            return False
        if reason == "base_failed":
            return item["base_result"] == "failed" or any(attempt["status"] == "failed" for attempt in item["attempts"])
        if reason in _ANOMALY_STATUS:
            return bool(item.get(f"{reason}_count", 0)) or any(observation["status"] == reason for attempt in item["attempts"] for observation in attempt["observations"])
        if reason != "all":
            return any(attempt["error_type"] == reason for attempt in item["attempts"])
        return True
    filtered = [item for item in items if matches(item)]
    if anomalies_first:
        filtered.sort(key=lambda item: (not item["has_anomaly"], item["position"]))
    result.update(total=len(filtered), page=page, page_size=page_size or len(filtered))
    result["items"] = filtered[(page - 1) * page_size:page * page_size] if page_size else filtered
    return result


def get_collection_run(db: Session, run_id: int) -> dict[str, object] | None:
    row = db.execute(select(CollectionRun, Competitor).join(Competitor, Competitor.id == CollectionRun.competitor_id).where(CollectionRun.id == run_id)).first()
    if row is None:
        return None
    run, competitor = row
    observations = db.scalars(select(OperatingMetricObservation).where(OperatingMetricObservation.collection_run_id == run.id).order_by(OperatingMetricObservation.metric_key)).all()
    add_input = db.scalar(select(CollectionAddInput).where(CollectionAddInput.batch_item_id == run.collection_batch_item_id)) if run.collection_batch_item_id is not None else None
    navigation = add_input if add_input is not None else run
    return {
        "id": run.id, "competitor_id": competitor.id, "title": competitor.title,
        "shop_name": competitor.shop_name, "offer_id": competitor.offer_id, "main_image_url": competitor.main_image_url,
        "collection_batch_item_id": run.collection_batch_item_id,
        "attempt_kind": run.attempt_kind, "attempt_number": run.attempt_number,
        "started_at": run.started_at, "finished_at": run.finished_at,
        "duration_seconds": duration_seconds(run.started_at, run.finished_at),
        "status": run.status, "operating_metrics_status": run.operating_metrics_status,
        "error_type": run.error_type, "error_message": run.error_message,
        "navigation_evidence_source": "add_input" if add_input is not None else "collection_run",
        "navigation_claimed_at": navigation.navigation_claimed_at, "navigation_confirmed_at": navigation.navigation_confirmed_at,
        "navigation_terminal_reason": navigation.navigation_terminal_reason,
        "observations": [{"metric_key": observation.metric_key, "status": observation.status, "raw_value": observation.raw_value, "reason": observation.reason, "source": observation.source, "observed_at": observation.observed_at} for observation in observations],
    }
