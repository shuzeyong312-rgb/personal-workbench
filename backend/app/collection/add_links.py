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
from app.models import CollectionAddInput, CollectionBatch, CollectionBatchItem, CollectionRun, Competitor, CompetitorGroup, ProductSnapshot, SkuSnapshot
from app.ownership import get_own_shop_name, identify_ownership
from app.settings import batch_config_values, get_competitor_monitoring_settings

REJECTED = {'invalid_url', 'duplicate_input', 'already_exists', 'identity_rejected'}
ERRORS = {'invalid_url': 'invalid_competitor_url', 'duplicate_input': 'duplicate_input', 'already_exists': 'competitor_already_exists'}


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
        item.operating_metrics_status = 'not_attempted'
        item.page_visits = int(row.navigation_confirmed_at is not None)
        item.page_visits_unknown = int(row.navigation_claimed_at is not None and row.navigation_confirmed_at is None)


def finalize_add_batch(db, batch, cause=None):
    rows = db.scalars(select(CollectionAddInput).where(CollectionAddInput.batch_id == batch.id).order_by(CollectionAddInput.position)).all()
    for row in rows:
        if row.result_code is None:
            result = 'interrupted' if row.started_at is not None else 'not_executed'
            set_input_result(db, row, result, cause or 'not_executed')
        else:
            # Rebuild candidate caches without reclassifying a rejection that has no Run.
            finished = row.finished_at
            set_input_result(db, row, row.result_code, row.error_code, row.sanitized_reason)
            row.finished_at = finished
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


def persist_added_product(db, batch, row, product):
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
    db.add(CollectionRun(competitor_id=competitor.id, collection_batch_item_id=item.id, attempt_number=1,
                         attempt_kind='first_pass', started_at=row.started_at, finished_at=at, status='success', operating_metrics_status='not_attempted'))
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
                    product = service.collect_product(url, offer_id, **kwargs)
                    with session_factory() as db:
                        persist_added_product(db, db.get(CollectionBatch, batch_id), db.get(CollectionAddInput, input_id), product)
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
    if attempt_kind != 'all' or reason != 'all' or final_result not in {'all', 'success', 'exception', 'pending', 'not_executed', 'business_rejected'} or anomaly not in {'all', 'current', 'none', 'rejected', 'verification_required', 'base_failed'}:
        raise HTTPException(422, {'code': 'incompatible_filter'})
    rows = db.execute(select(CollectionAddInput, CollectionBatchItem, Competitor)
                      .outerjoin(CollectionBatchItem, CollectionBatchItem.id == CollectionAddInput.batch_item_id)
                      .outerjoin(Competitor, Competitor.id == CollectionAddInput.related_competitor_id)
                      .where(CollectionAddInput.batch_id == batch.id).order_by(CollectionAddInput.position)).all()
    summary = input_summary([row for row, _, _ in rows], batch.planned_products)
    item_ids = [item.id for _, item, _ in rows if item is not None]
    runs = db.scalars(select(CollectionRun).where(CollectionRun.collection_batch_item_id.in_(item_ids)).order_by(CollectionRun.id)).all() if item_ids else []
    runs_by_item = {}
    for run in runs:
        runs_by_item.setdefault(run.collection_batch_item_id, []).append(run)
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
            'technical_exception_products': 0, 'anomaly_products': summary['anomaly_inputs'],
            'page_visits': visits, 'page_visits_unknown': unknown, 'retry_visits': 0, 'verification_resume_visits': 0,
            'attempts_started': len(runs), 'input_summary': summary,
            'duration_seconds': duration_seconds(batch.started_at, batch.finished_at)}
    items = []
    for row, item, competitor in rows:
        current = row.result_code in {'technical_failed', 'verification_required', 'interrupted'}
        rejected = row.result_code in REJECTED
        if input_result != 'all' and row.result_code != input_result:
            continue
        if final_result == 'success' and row.result_code != 'added' or final_result == 'exception' and not current or final_result == 'business_rejected' and not rejected or final_result == 'pending' and row.result_code is not None or final_result == 'not_executed' and row.result_code != 'not_executed':
            continue
        if anomaly == 'base_failed' and row.result_code != 'technical_failed' or anomaly == 'current' and not current or anomaly == 'none' and not (row.result_code == 'added' or rejected) or anomaly == 'rejected' and not rejected or anomaly == 'verification_required' and row.result_code != 'verification_required':
            continue
        if search and not any(search.strip().lower() in str(value or '').lower() for value in (row.input_text, row.offer_id, competitor.title if competitor else None, competitor.shop_name if competitor else None)):
            continue
        attempts = [{'id': run.id, 'attempt_number': run.attempt_number, 'attempt_kind': run.attempt_kind,
                     'started_at': run.started_at, 'finished_at': run.finished_at, 'status': run.status,
                     'operating_metrics_status': 'not_attempted', 'error_message': run.error_message, 'observations': [],
                     'navigation_claimed_at': row.navigation_claimed_at, 'navigation_confirmed_at': row.navigation_confirmed_at,
                     'navigation_evidence_source': 'add_input'} for run in runs_by_item.get(row.batch_item_id, [])]
        items.append({'position': row.position, 'source_line': row.source_line, 'input_text': row.input_text,
                      'offer_id': row.offer_id, 'title': competitor.title if competitor else None,
                      'shop_name': competitor.shop_name if competitor else None, 'main_image_url': competitor.main_image_url if competitor else None,
                      'competitor_id': row.related_competitor_id, 'identity_state': item.identity_state if item else 'removed' if row.identity_removed else 'pending',
                      'identity_removed': row.identity_removed, 'result_code': row.result_code, 'error_code': row.error_code,
                      'sanitized_reason': row.sanitized_reason, 'final_result': item.final_result if item else None,
                      'base_result': item.base_result if item else 'not_attempted', 'has_anomaly': current, 'had_anomaly': current,
                      'started_at': row.started_at, 'finished_at': row.finished_at,
                      'duration_seconds': duration_seconds(row.started_at, row.finished_at),
                      'page_visits': int(row.navigation_confirmed_at is not None),
                      'page_visits_unknown': int(row.navigation_claimed_at is not None and row.navigation_confirmed_at is None),
                      'navigation_claimed_at': row.navigation_claimed_at, 'navigation_confirmed_at': row.navigation_confirmed_at,
                      'navigation_evidence_source': 'add_input', 'attempts_started': len(attempts), 'attempts': attempts,
                      'retry_visits': 0, 'technical_exception_count': 0})
    if anomalies_first:
        items.sort(key=lambda value: (not value['has_anomaly'], value['position']))
    size = page_size or max(1, len(items))
    return {**base, 'summary': base.copy(), 'protection_details': batch.protection_details, 'circuit_breaker_cancelled': 0,
            'items': items[(page - 1) * size:page * size], 'total': len(items), 'page': page, 'page_size': size}
