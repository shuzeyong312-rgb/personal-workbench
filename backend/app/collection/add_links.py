"""Add-submission facts and operations used by the sole collection worker."""
from collections import Counter
from contextlib import ExitStack
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from time import monotonic

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.collection import service
from app.collection.parser_1688 import parse_1688_url
from app.collection.types import CollectionPageResult, OperatingMetricData
from app.models import CollectionAddInput, CollectionBatch, CollectionBatchItem, CollectionRun, Competitor, CompetitorGroup, OperatingMetricObservation, ProductSnapshot, SkuSnapshot
from app.ownership import get_own_shop_name, identify_ownership
from app.settings import batch_config_values, get_competitor_monitoring_settings

REJECTED = {'invalid_url', 'duplicate_input', 'already_exists', 'identity_rejected'}
ERRORS = {'invalid_url': 'invalid_competitor_url', 'duplicate_input': 'duplicate_input', 'already_exists': 'competitor_already_exists'}
METRIC_KEYS = {'listing_time', 'monthly_deal', 'monthly_dropship', 'annual_units', 'annual_orders', 'review_count', 'positive_rate', 'pickup_rate'}
METRIC_SOURCE = '1688_official_procurement_assistant_top'
METRIC_TECHNICAL_STATUSES = {'source_unavailable', 'loading', 'read_failed'}


def now():
    return datetime.now(timezone.utc)


def input_summary(rows, candidate_total):
    counts = Counter(row.result_code for row in rows)
    result = {key: counts[key] for key in ('added', 'technical_failed', 'verification_required', 'not_executed', 'interrupted')}
    result['business_rejected'] = sum(counts[key] for key in REJECTED)
    result['total'] = result['submitted_inputs'] = len(rows)
    result['candidate_total'] = candidate_total
    result['pending'] = result['pending_inputs'] = counts[None]
    result['processed'] = sum(result[key] for key in ('added', 'business_rejected', 'technical_failed', 'verification_required', 'interrupted'))
    result['remaining'] = len(rows) - result['processed']
    result['anomaly_inputs'] = result['technical_failed'] + result['verification_required'] + result['interrupted']
    return result


def set_input_result(db, row, result, code=None, reason=None):
    row.result_code, row.error_code = result, code
    row.sanitized_reason = reason
    row.finished_at = now()
    if row.batch_item_id is not None:
        item = db.get(CollectionBatchItem, row.batch_item_id)
        item.final_result = ('business_rejected' if result in REJECTED else
                             {'added': 'first_pass_success', 'verification_required': 'verification_required', 'not_executed': 'not_executed'}.get(result, 'final_failed'))
        item.base_result = 'success' if result == 'added' else 'failed' if result == 'technical_failed' else 'not_attempted'
        item.execution_status = 'not_executed' if result == 'not_executed' else 'failed' if result in {'technical_failed', 'interrupted'} else 'completed'
        item.stop_reason = code
        if result != 'added':
            item.operating_metrics_status = 'not_attempted'
        item.page_visits = int(row.navigation_confirmed_at is not None)
        item.page_visits_unknown = int(row.navigation_claimed_at is not None and row.navigation_confirmed_at is None)


def finalize_add_batch(db, batch, cause=None):
    rows = db.scalars(select(CollectionAddInput).where(CollectionAddInput.batch_id == batch.id).order_by(CollectionAddInput.position)).all()
    for row in rows:
        if row.result_code is None:
            result = 'interrupted' if row.started_at is not None else 'not_executed'
            set_input_result(db, row, result, cause or 'not_executed')
    summary = input_summary(rows, batch.planned_products)
    outcome = cause or ('success' if summary['added'] == summary['total'] else 'partial_failure' if summary['added'] else 'collect_failed')
    batch.lifecycle_status, batch.outcome_code, batch.finished_at = 'terminal', outcome, now()
    if cause:
        batch.protection_reason = cause
    return summary


def admission_error(code, task_id, status=503):
    raise HTTPException(status, {'code': code, 'submission_id': task_id, 'task_id': None,
                                'accepted': False if code == 'admission_pending' else None,
                                'admission_state': 'pending' if code == 'admission_pending' else 'unknown'}, headers={'Retry-After': '1'})


def _reconcile(db, task_id, entry, runtime):
    if entry.get('active') or not entry.get('transaction_closed'):
        admission_error('admission_unknown', task_id)
    with runtime._lock:
        if entry.get('reconciling'):
            admission_error('admission_unknown', task_id)
        entry['reconciling'] = True
    try:
        db.rollback()
        batch = db.scalar(select(CollectionBatch).where(CollectionBatch.task_id == task_id))
        if batch is not None and batch.lifecycle_status != 'terminal' and (not entry.get('dispatched') or not runtime.runner_active):
            finalize_add_batch(db, batch, 'infrastructure_error')
            db.commit()
        with runtime._lock:
            runtime.admissions.pop(task_id, None)
        if entry.get('reservation') and runtime.owns_reservation(entry['reservation']):
            runtime.finish('collect_failed')
            runtime.mark_runner_stopped()
        return batch
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        admission_error('admission_unknown', task_id)
    finally:
        entry['reconciling'] = False


def find_submission(db, task_id, runtime):
    with runtime._lock:
        entry = runtime.admissions.get(task_id)
    if entry and entry['state'] == 'unknown':
        return _reconcile(db, task_id, entry, runtime)
    try:
        batch = db.scalar(select(CollectionBatch).where(CollectionBatch.task_id == task_id))
    except Exception:
        db.rollback()
        admission_error('admission_unknown', task_id)
    if batch is None and entry:
        admission_error('admission_pending', task_id, 202)
    return batch


def admit_add(db, task_id, inputs, group_id, runtime, *, synchronous=False):
    fingerprint = sha256(json.dumps({'inputs': inputs, 'group_id': group_id}, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    owner = object()
    with runtime._lock:
        entry = runtime.admissions.get(task_id)
        if entry and entry['fingerprint'] != fingerprint:
            raise HTTPException(409, {'code': 'idempotency_conflict', 'message': '同一提交标识的内容不同'})
        if entry is None:
            entry = {'fingerprint': fingerprint, 'owner': owner, 'state': 'pending', 'active': True, 'transaction_closed': True, 'dispatched': False}
            runtime.admissions[task_id] = entry
        owns = entry['owner'] is owner
    if not owns:
        batch = find_submission(db, task_id, runtime)
        if batch is None:
            # Only a proven rollback can reach here. Retry with the same identity.
            return admit_add(db, task_id, inputs, group_id, runtime, synchronous=synchronous)
        if batch.request_fingerprint != fingerprint:
            raise HTTPException(409, {'code': 'idempotency_conflict'})
        return batch.id, False, None
    reservation = None
    committing = False
    resolved = False
    try:
        batch = db.scalar(select(CollectionBatch).where(CollectionBatch.task_id == task_id))
        if batch is not None:
            if batch.trigger_kind != 'add_links' or batch.request_fingerprint != fingerprint:
                raise HTTPException(409, {'code': 'idempotency_conflict'})
            resolved = True
            return batch.id, False, None
        if get_own_shop_name(db) is None:
            raise HTTPException(409, {'code': 'own_shop_name_not_configured', 'message': '请先在系统设置中配置我方店铺名称'})
        if group_id is not None and db.get(CompetitorGroup, group_id) is None:
            raise HTTPException(404, {'code': 'competitor_group_not_found', 'message': '竞品组不存在'})
        config = service.BatchConfig(**batch_config_values(get_competitor_monitoring_settings(db)))
        db.rollback()
        if not service.acquire_collection_slot(runtime=runtime):
            raise HTTPException(409, {'code': 'collection_in_progress', 'message': '已有商品正在采集，请稍后重试'})
        try:
            if not runtime.reserve_add(list(range(len(inputs))), config):
                raise HTTPException(409, {'code': 'collection_in_progress'})
            reservation = runtime.reservation_token()
            entry['reservation'] = reservation
            at = now()
            batch = CollectionBatch(task_id=task_id, trigger_kind='add_links', request_fingerprint=fingerprint,
                                    created_at=at, started_at=at, lifecycle_status='created', planned_products=0,
                                    settings_snapshot={**asdict(config), 'add_group_id': group_id, 'add_synchronous': synchronous})
            db.add(batch)
            db.flush()
            seen = {}
            for position, value in enumerate(inputs):
                row = CollectionAddInput(batch_id=batch.id, position=position, source_line=value['source_line'], input_text=value['text'])
                db.add(row)
                db.flush()
                try:
                    offer_id, url = parse_1688_url(value['text'])
                except ValueError:
                    set_input_result(db, row, 'invalid_url', 'invalid_competitor_url', '链接格式无效')
                    continue
                row.offer_id, row.normalized_url = offer_id, url
                if offer_id in seen:
                    row.duplicate_of_input_id = seen[offer_id]
                    set_input_result(db, row, 'duplicate_input', 'duplicate_input', '本次提交内重复')
                    continue
                seen[offer_id] = row.id
                existing = db.scalar(select(Competitor).where(Competitor.platform == '1688', Competitor.offer_id == offer_id))
                if existing is not None:
                    row.related_competitor_id = existing.id
                    set_input_result(db, row, 'already_exists', 'competitor_already_exists', '商品已存在')
                    continue
                item = CollectionBatchItem(batch_id=batch.id, position=position, identity_state='pending')
                db.add(item)
                db.flush()
                row.batch_item_id = item.id
                batch.planned_products += 1
            committing = True
            entry['transaction_closed'] = False
            db.commit()
            entry['transaction_closed'] = True
            runtime.bind_batch(batch)
            rows = db.scalars(select(CollectionAddInput).where(CollectionAddInput.batch_id == batch.id)).all()
            runtime.set_input_progress(input_summary(rows, batch.planned_products))
            resolved = True
            return batch.id, True, config
        finally:
            service.COLLECTION_LOCK.release()
    except HTTPException:
        db.rollback()
        resolved = True
        if reservation is not None:
            runtime.finish('collect_failed')
        raise
    except IntegrityError:
        db.rollback()
        entry['transaction_closed'] = True
        batch = db.scalar(select(CollectionBatch).where(CollectionBatch.task_id == task_id))
        if batch is not None:
            resolved = True
            if reservation is not None:
                runtime.finish('collect_failed')
            if batch.request_fingerprint != fingerprint:
                raise HTTPException(409, {'code': 'idempotency_conflict'})
            return batch.id, False, None
        if not committing:
            resolved = True
            if reservation is not None:
                runtime.finish('collect_failed')
        admission_error('admission_unknown', task_id)
    except Exception:
        try:
            db.rollback()
            entry['transaction_closed'] = True
        except Exception:
            entry['transaction_closed'] = False
        if not committing:
            resolved = entry['transaction_closed']
            if reservation is not None and resolved:
                runtime.finish('collect_failed')
        admission_error('admission_unknown', task_id)
    finally:
        with runtime._lock:
            entry['active'] = False
            if not resolved:
                entry['state'] = 'unknown'
            elif reservation is None or not (reservation == runtime._active_reservation and runtime.runner_active):
                runtime.admissions.pop(task_id, None)


def dispatch_add(session_factory, batch_id, runtime, config, *, synchronous=False):
    with session_factory() as db:
        batch = db.get(CollectionBatch, batch_id)
        task_id = batch.task_id
        no_candidates = batch.planned_products == 0
    with runtime._lock:
        entry = runtime.admissions.get(task_id)
        if entry is None or entry.get('dispatched'):
            return
        entry['dispatched'] = True
    try:
        if synchronous or no_candidates:
            service.run_batch_collection(session_factory, [], runtime, batch_reservation=runtime.reservation_token(), config=config, persisted_batch_id=batch_id)
        else:
            service.start_batch_task(session_factory, [], runtime, batch_reservation=runtime.reservation_token(), config=config, persisted_batch_id=batch_id)
    except Exception:
        try:
            with session_factory() as db:
                batch = db.get(CollectionBatch, batch_id)
                finalize_add_batch(db, batch, 'infrastructure_error')
                db.commit()
            runtime.finish('collect_failed')
        except Exception:
            with runtime._lock:
                entry['state'] = 'unknown'
                entry['active'] = False
                entry['transaction_closed'] = True
            admission_error('admission_unknown', task_id)
        raise
    finally:
        with runtime._lock:
            if entry['state'] != 'unknown':
                runtime.admissions.pop(task_id, None)


def add_metrics_status(observations):
    if not observations:
        return 'not_attempted'
    statuses = [item.status for item in observations]
    observed = statuses.count('observed')
    if len(statuses) == 8 and observed == 8:
        return 'success'
    if observed:
        return 'partial'
    if all(status == 'placeholder' for status in statuses):
        return 'no_values'
    return 'failed'


def validate_add_metrics(observations, offer_id):
    if not isinstance(observations, list) or len(observations) > 8:
        raise service.CollectionError('offer_id_mismatch', '经营指标无法安全关联到目标商品')
    keys = set()
    for item in observations:
        if not isinstance(item, OperatingMetricData) or not isinstance(item.metric_key, str) or item.metric_key not in METRIC_KEYS or item.metric_key in keys:
            raise service.CollectionError('offer_id_mismatch', '经营指标无法安全关联到目标商品')
        if item.offer_id != offer_id or item.source != METRIC_SOURCE:
            raise service.CollectionError('offer_id_mismatch', '经营指标身份或来源校验失败')
        if not isinstance(item.status, str) or item.status not in {'observed', 'placeholder', *METRIC_TECHNICAL_STATUSES}:
            raise service.CollectionError('offer_id_mismatch', '经营指标状态无效')
        if item.status in {'observed', 'placeholder'}:
            if not isinstance(item.raw_value, str) or not item.raw_value or len(item.raw_value) > 512:
                raise service.CollectionError('offer_id_mismatch', '经营指标原始值无效')
        elif item.raw_value is not None:
            raise service.CollectionError('offer_id_mismatch', '经营指标原始值无效')
        if not isinstance(item.observed_at, datetime) or (item.reason is not None and (not isinstance(item.reason, str) or len(item.reason) > 512)):
            raise service.CollectionError('offer_id_mismatch', '经营指标观察记录无效')
        keys.add(item.metric_key)
    return observations


def persist_added_product(db, batch, row, page_result):
    if not isinstance(page_result, CollectionPageResult) or page_result.offer_id != row.offer_id or page_result.product is None:
        raise service.CollectionError('offer_id_mismatch', '页面结果与目标商品不一致')
    product = page_result.product
    observations = validate_add_metrics(page_result.operating_metrics, row.offer_id)
    metrics_status = add_metrics_status(observations)
    shop = get_own_shop_name(db)
    group_id = batch.settings_snapshot['add_group_id']
    if shop is None:
        raise service.CollectionError('own_shop_name_not_configured', '我方店铺设置已改变')
    if db.scalar(select(Competitor).where(Competitor.platform == '1688', Competitor.offer_id == row.offer_id)):
        raise service.CollectionError('competitor_already_exists', '商品已存在')
    if group_id is not None and db.get(CompetitorGroup, group_id) is None:
        raise service.CollectionError('competitor_group_not_found', '竞品组不存在')
    ownership = identify_ownership(product.shop_name, shop)
    if ownership is None:
        raise service.CollectionError('shop_name_unavailable', '无法确认店铺名称')
    if ownership == 'self' and group_id is not None and db.scalar(select(Competitor.id).where(Competitor.group_id == group_id, Competitor.group_role == 'own')):
        raise service.CollectionError('own_product_already_bound', '该竞品组已绑定我方商品')
    at = now()
    competitor = Competitor(platform='1688', offer_id=row.offer_id, url=row.normalized_url, group_id=group_id,
                            group_role='own' if ownership == 'self' and group_id is not None else 'competitor',
                            ownership=ownership, title=product.title, shop_name=product.shop_name, main_image_url=product.main_image_url,
                            status=product.product_status, is_active=True, created_at=at, updated_at=at, last_collected_at=product.captured_at)
    db.add(competitor)
    db.flush()
    db.add(ProductSnapshot(competitor_id=competitor.id, captured_at=product.captured_at, title=product.title,
                           shop_name=product.shop_name, main_image_url=product.main_image_url, image_urls=product.image_urls,
                           price_min=product.price_min, price_max=product.price_max, min_order_quantity=product.min_order_quantity,
                           product_status=product.product_status, collection_source=product.collection_source,
                           skus=[SkuSnapshot(sku_id=sku.sku_id, sku_name=sku.sku_name, stock=sku.stock, price=sku.price) for sku in product.skus]))
    item = db.get(CollectionBatchItem, row.batch_item_id)
    item.competitor_id, item.identity_state, item.attempts_started = competitor.id, 'linked', 1
    run = CollectionRun(competitor_id=competitor.id, collection_batch_item_id=item.id, attempt_number=1,
                         attempt_kind='first_pass', started_at=row.started_at, finished_at=at, status='success', operating_metrics_status=metrics_status)
    db.add(run)
    db.flush()
    db.add_all([OperatingMetricObservation(
        competitor_id=competitor.id, collection_run_id=run.id, platform='1688', offer_id=row.offer_id,
        metric_key=metric.metric_key, status=metric.status, raw_value=metric.raw_value,
        source=metric.source, observed_at=metric.observed_at, reason=metric.reason,
    ) for metric in observations])
    item.operating_metrics_status = metrics_status
    item.placeholder_count = sum(metric.status == 'placeholder' for metric in observations)
    item.source_unavailable_count = sum(metric.status == 'source_unavailable' for metric in observations)
    item.loading_count = sum(metric.status == 'loading' for metric in observations)
    item.read_failed_count = sum(metric.status == 'read_failed' for metric in observations)
    item.technical_exception_count = sum(metric.status in METRIC_TECHNICAL_STATUSES for metric in observations)
    row.related_competitor_id = competitor.id
    set_input_result(db, row, 'added')
    db.commit()


def execute_add_batch(session_factory, batch_id, runtime, reservation, config):
    config = config or service.BatchConfig()
    if not service.acquire_collection_slot(batch_reservation=reservation, runtime=runtime):
        return
    context = None
    cause = None
    try:
        with session_factory() as db:
            batch = db.get(CollectionBatch, batch_id)
            if batch is None or batch.lifecycle_status != 'created':
                return
            batch.lifecycle_status = 'running'
            db.commit()
            runtime.set_persisted_batch_state('running')
            sync = batch.settings_snapshot.get('add_synchronous', False)
            input_ids = db.scalars(select(CollectionAddInput.id).where(CollectionAddInput.batch_id == batch_id, CollectionAddInput.result_code.is_(None)).order_by(CollectionAddInput.position)).all()
        with ExitStack() as stack:
            playwright = None
            def ensure_context():
                nonlocal context, playwright
                if not sync and context is None:
                    if playwright is None:
                        playwright = stack.enter_context(service.sync_playwright())
                    context = service._launch_context(playwright)
                    runtime.set_browser_open(True)
                    service.move_context_offscreen(context)
            def pause():
                nonlocal context
                if runtime.pause_requested():
                    service._close_quietly(context)
                    context = None
                    runtime.set_browser_open(False)
                    runtime.set_current_input(None)
                    runtime.mark_paused()
                    return runtime.wait_for_resume()
                return not runtime.stop_requested()
            def wait(seconds):
                remaining = seconds
                while remaining > 0 and not runtime.stop_requested():
                    if not pause():
                        return False
                    at = monotonic()
                    runtime.wait_for_stop(min(remaining, .1))
                    if not runtime.pause_requested():
                        remaining -= monotonic() - at
                return not runtime.stop_requested()
            for index, input_id in enumerate(input_ids):
                if not pause():
                    cause = 'user_ended' if runtime.end_requested() else 'interrupted'
                    break
                ensure_context()
                with session_factory() as db:
                    row = db.get(CollectionAddInput, input_id)
                    row.started_at = now()
                    db.get(CollectionBatchItem, row.batch_item_id).execution_status = 'running'
                    db.commit()
                    position, url, offer_id = row.position, row.normalized_url, row.offer_id
                runtime.set_current_input(position)
                def navigation(confirmed=False):
                    with session_factory() as db:
                        row = db.get(CollectionAddInput, input_id)
                        if confirmed:
                            if row.navigation_claimed_at is None:
                                raise service.CollectionError('collection_save_failed', '导航声明缺失')
                            row.navigation_confirmed_at = now()
                            db.get(CollectionBatchItem, row.batch_item_id).page_visits = 1
                        else:
                            if row.navigation_claimed_at is not None:
                                raise service.CollectionError('collection_save_failed', '禁止重复导航')
                            row.navigation_claimed_at = now()
                        db.commit()
                    if confirmed:
                        runtime.record_page_visit(None)
                        runtime.record_external_access()
                try:
                    kwargs = {'browser_context': context, 'on_navigation_claim': navigation, 'on_navigation_confirmed': lambda: navigation(True)}
                    kwargs['include_page_result'] = True
                    page_result = service.collect_product(url, offer_id, **kwargs)
                    with session_factory() as db:
                        persist_added_product(db, db.get(CollectionBatch, batch_id), db.get(CollectionAddInput, input_id), page_result)
                except Exception as exc:
                    if isinstance(exc, service.CollectionError):
                        code, reason = exc.code, exc.message
                    elif isinstance(exc, IntegrityError):
                        code, reason = 'collection_save_failed', '商品数据保存失败'
                        with session_factory() as db:
                            if db.scalar(select(Competitor.id).where(Competitor.platform == '1688', Competitor.offer_id == offer_id)):
                                code, reason = 'competitor_already_exists', '商品已存在'
                    else:
                        code, reason = 'collection_save_failed', '商品数据保存失败'
                    result = ('already_exists' if code == 'competitor_already_exists' else 'identity_rejected' if code in {'shop_name_unavailable', 'own_product_already_bound', 'competitor_group_not_found', 'own_shop_name_not_configured'} else 'verification_required' if code in {'1688_verification_required', '1688_login_required'} else 'technical_failed')
                    with session_factory() as db:
                        row = db.get(CollectionAddInput, input_id)
                        if row.result_code != 'added':
                            set_input_result(db, row, result, code, reason)
                            db.commit()
                        else:
                            result = 'added'
                    if result == 'verification_required':
                        cause = 'verification_required'
                with session_factory() as db:
                    batch = db.get(CollectionBatch, batch_id)
                    rows = db.scalars(select(CollectionAddInput).where(CollectionAddInput.batch_id == batch_id)).all()
                    runtime.set_input_progress(input_summary(rows, batch.planned_products))
                    if db.get(CollectionAddInput, input_id).result_code == 'added':
                        runtime.record_attempt_started()
                    with runtime._lock:
                        runtime.page_visits_unknown = sum(row.navigation_claimed_at is not None and row.navigation_confirmed_at is None for row in rows)
                runtime.set_current_input(None)
                if cause:
                    break
                if index + 1 < len(input_ids):
                    rest = (index + 1) % config.continuous_collection_count == 0
                    if rest:
                        runtime.enter_resting(config.batch_rest_seconds)
                    waited = runtime.wait_for_resting(config.batch_rest_seconds, on_pause=pause) if rest else wait(config.item_interval_seconds)
                    if not waited:
                        cause = 'user_ended' if runtime.end_requested() else 'interrupted'
                        break
                    if rest:
                        runtime.set_running()
    except Exception:
        cause = 'infrastructure_error'
    finally:
        service._close_quietly(context)
        runtime.set_browser_open(False)
        try:
            with session_factory() as db:
                batch = db.get(CollectionBatch, batch_id)
                if batch is not None and batch.lifecycle_status != 'terminal':
                    summary = finalize_add_batch(db, batch, cause)
                    db.commit()
                    runtime.set_input_progress(summary)
                    rows = db.scalars(select(CollectionAddInput).where(CollectionAddInput.batch_id == batch_id)).all()
                    with runtime._lock:
                        runtime.page_visits = sum(row.navigation_confirmed_at is not None for row in rows)
                        runtime.page_visits_unknown = sum(row.navigation_claimed_at is not None and row.navigation_confirmed_at is None for row in rows)
                    outcome = batch.outcome_code
                    runtime.finish('collect_failed' if outcome in {'infrastructure_error', 'interrupted'} else outcome,
                                   status='stopped' if outcome == 'user_ended' else 'verification_required' if outcome == 'verification_required' else 'completed')
                    runtime.set_persisted_batch_state('terminal', outcome)
        finally:
            runtime.mark_runner_stopped()
            service.COLLECTION_LOCK.release()

def add_task_detail(db, batch, *, search=None, final_result='all', anomaly='all', input_result='all', attempt_kind='all', reason='all', anomalies_first=False, page=1, page_size=None):
    from app.collection.batch_records import duration_seconds
    allowed_reasons = {'all', 'base_failed', 'placeholder', *METRIC_TECHNICAL_STATUSES}
    if attempt_kind != 'all' or reason not in allowed_reasons or final_result not in {'all', 'success', 'exception', 'pending', 'not_executed', 'business_rejected'} or anomaly not in {'all', 'current', 'none', 'rejected', 'verification_required', 'base_failed', 'placeholder', *METRIC_TECHNICAL_STATUSES}:
        raise HTTPException(422, {'code': 'incompatible_filter'})
    rows = db.execute(select(CollectionAddInput, CollectionBatchItem, Competitor)
                      .outerjoin(CollectionBatchItem, CollectionBatchItem.id == CollectionAddInput.batch_item_id)
                      .outerjoin(Competitor, Competitor.id == CollectionAddInput.related_competitor_id)
                      .where(CollectionAddInput.batch_id == batch.id).order_by(CollectionAddInput.position)).all()
    summary = input_summary([row for row, _, _ in rows], batch.planned_products)
    item_ids = [item.id for _, item, _ in rows if item is not None]
    runs = db.scalars(select(CollectionRun).where(CollectionRun.collection_batch_item_id.in_(item_ids)).order_by(CollectionRun.id)).all() if item_ids else []
    runs_by_item = {}
    run_ids = []
    for run in runs:
        runs_by_item.setdefault(run.collection_batch_item_id, []).append(run)
        run_ids.append(run.id)
    observations_by_run = {}
    if run_ids:
        observations = db.scalars(select(OperatingMetricObservation).where(OperatingMetricObservation.collection_run_id.in_(run_ids)).order_by(OperatingMetricObservation.metric_key)).all()
        for observation in observations:
            observations_by_run.setdefault(observation.collection_run_id, []).append(observation)
    observations_by_item = {
        item_id: [observation for run in item_runs for observation in observations_by_run.get(run.id, [])]
        for item_id, item_runs in runs_by_item.items()
    }
    metric_counts_by_item = {
        item.id: Counter({status: getattr(item, status + '_count') for status in METRIC_TECHNICAL_STATUSES | {'placeholder'}})
        if item.identity_state == 'removed' else Counter(value.status for value in observations_by_item.get(item.id, []))
        for _, item, _ in rows if item is not None
    }
    technical_items = {item_id for item_id, counts in metric_counts_by_item.items() if any(counts[status] for status in METRIC_TECHNICAL_STATUSES)}
    counts = Counter(item.final_result or 'pending' for _, item, _ in rows if item is not None)
    visits = sum(row.navigation_confirmed_at is not None for row, _, _ in rows)
    unknown = sum(row.navigation_claimed_at is not None and row.navigation_confirmed_at is None for row, _, _ in rows)
    completed = sum(count for key, count in counts.items() if key not in {'pending', 'not_executed'})
    base = {'task_id': batch.task_id, 'batch_id': batch.id, 'task_kind': 'add_links', 'trigger_kind': 'add_links',
            'created_at': batch.created_at, 'started_at': batch.started_at, 'finished_at': batch.finished_at,
            'lifecycle_status': batch.lifecycle_status, 'outcome_code': batch.outcome_code, 'batch_outcome_code': batch.outcome_code,
            'planned_products': batch.planned_products, 'counts': dict(counts), 'completed': completed,
            'remaining': batch.planned_products - completed, 'succeeded': summary['added'],
            'final_failed': counts['final_failed'], 'base_failed_products': summary['technical_failed'],
            'technical_exception_products': len(technical_items), 'anomaly_products': 0,
            'page_visits': visits, 'page_visits_unknown': unknown, 'retry_visits': 0, 'verification_resume_visits': 0,
            'attempts_started': len(runs), 'input_summary': summary,
            'duration_seconds': duration_seconds(batch.started_at, batch.finished_at)}
    items = []
    anomaly_rows = set()
    for row, item, competitor in rows:
        input_current = row.result_code in {'technical_failed', 'verification_required', 'interrupted'}
        metric_counts = metric_counts_by_item.get(item.id, Counter()) if item is not None else Counter()
        metric_current = any(metric_counts[status] for status in METRIC_TECHNICAL_STATUSES)
        current = input_current or metric_current
        if current:
            anomaly_rows.add(row.id)
        rejected = row.result_code in REJECTED
        if input_result != 'all' and row.result_code != input_result:
            continue
        if final_result == 'success' and row.result_code != 'added' or final_result == 'exception' and not current or final_result == 'business_rejected' and not rejected or final_result == 'pending' and row.result_code is not None or final_result == 'not_executed' and row.result_code != 'not_executed':
            continue
        if anomaly == 'base_failed' and row.result_code != 'technical_failed' or anomaly == 'current' and not current or anomaly == 'none' and (row.result_code not in ({'added'} | REJECTED) or current) or anomaly == 'rejected' and not rejected or anomaly == 'verification_required' and row.result_code != 'verification_required' or anomaly in METRIC_TECHNICAL_STATUSES | {'placeholder'} and not metric_counts[anomaly]:
            continue
        if reason in METRIC_TECHNICAL_STATUSES | {'placeholder'} and not metric_counts[reason]:
            continue
        if reason == 'base_failed' and row.result_code != 'technical_failed':
            continue
        if search and not any(search.strip().lower() in str(value or '').lower() for value in (row.input_text, row.offer_id, competitor.title if competitor else None, competitor.shop_name if competitor else None)):
            continue
        attempts = [{'id': run.id, 'attempt_number': run.attempt_number, 'attempt_kind': run.attempt_kind,
                     'started_at': run.started_at, 'finished_at': run.finished_at, 'status': run.status,
                     'operating_metrics_status': run.operating_metrics_status, 'error_message': run.error_message,
                     'observations': [{'metric_key': value.metric_key, 'status': value.status, 'raw_value': value.raw_value,
                                       'source': value.source, 'observed_at': value.observed_at, 'reason': value.reason}
                                      for value in observations_by_run.get(run.id, [])],
                     'navigation_claimed_at': row.navigation_claimed_at, 'navigation_confirmed_at': row.navigation_confirmed_at,
                     'navigation_evidence_source': 'add_input'} for run in runs_by_item.get(row.batch_item_id, [])]
        items.append({'position': row.position, 'source_line': row.source_line, 'input_text': row.input_text,
                      'offer_id': row.offer_id, 'title': competitor.title if competitor else None,
                      'shop_name': competitor.shop_name if competitor else None, 'main_image_url': competitor.main_image_url if competitor else None,
                      'competitor_id': row.related_competitor_id, 'identity_state': item.identity_state if item else 'removed' if row.identity_removed else 'pending',
                      'identity_removed': row.identity_removed, 'result_code': row.result_code, 'error_code': row.error_code,
                      'sanitized_reason': row.sanitized_reason, 'final_result': item.final_result if item else None,
                      'base_result': item.base_result if item else 'not_attempted', 'operating_metrics_status': item.operating_metrics_status if item else 'not_attempted', 'has_anomaly': current, 'had_anomaly': current,
                      'started_at': row.started_at, 'finished_at': row.finished_at,
                      'duration_seconds': duration_seconds(row.started_at, row.finished_at),
                      'page_visits': int(row.navigation_confirmed_at is not None),
                      'page_visits_unknown': int(row.navigation_claimed_at is not None and row.navigation_confirmed_at is None),
                      'navigation_claimed_at': row.navigation_claimed_at, 'navigation_confirmed_at': row.navigation_confirmed_at,
                      'navigation_evidence_source': 'add_input', 'attempts_started': len(attempts), 'attempts': attempts,
                      'retry_visits': 0, 'technical_exception_count': sum(metric_counts[status] for status in METRIC_TECHNICAL_STATUSES),
                      'placeholder_count': metric_counts['placeholder'],
                      'source_unavailable_count': metric_counts['source_unavailable'],
                      'loading_count': metric_counts['loading'],
                      'read_failed_count': metric_counts['read_failed']})
    base['anomaly_products'] = len(anomaly_rows)
    if anomalies_first:
        items.sort(key=lambda value: (not value['has_anomaly'], value['position']))
    size = page_size or max(1, len(items))
    return {**base, 'summary': base.copy(), 'protection_details': batch.protection_details, 'circuit_breaker_cancelled': 0,
            'items': items[(page - 1) * size:page * size], 'total': len(items), 'page': page, 'page_size': size}
