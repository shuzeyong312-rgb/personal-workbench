from contextlib import nullcontext
from threading import Event, Thread
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, event
from sqlalchemy.orm import sessionmaker

from app import competitors as api_module
from app.collection import service
from app.collection.parser_1688 import CollectionParseError
from app.collection.types import CollectionPageResult
from app.database import get_db
from app.main import app
from app.models import Base, CollectionAddInput, CollectionBatch, CollectionBatchItem, CollectionRun, Competitor, OperatingMetricObservation, ProductSnapshot
from test_collection_api import product


@pytest.fixture()
def client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'isolated.sqlite').as_posix()}", connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    def database():
        with factory() as db:
            yield db
    monkeypatch.setenv('PERSONAL_WORKBENCH_DISABLE_SCHEDULER', '1')
    app.dependency_overrides[get_db] = database
    app.state.collection_session_factory = factory
    with TestClient(app) as api:
        api.put('/api/settings/own-shop-name', json={'own_shop_name': '测试店铺'})
        yield api, factory
    app.dependency_overrides.clear()
    app.state.collection_session_factory = None
    assert not service.BATCH_RUNTIME.is_busy()
    engine.dispose()


def payload(*values, task_id=None):
    return {'submission_id': task_id or str(uuid4()), 'inputs': [{'text': value, 'source_line': i + 1} for i, value in enumerate(values)], 'group_id': None}


def fake_collector(_url, offer_id, **callbacks):
    callbacks['on_navigation_claim']()
    callbacks['on_navigation_confirmed']()
    return product(offer_id)


def test_add_links_accepts_real_page_result_and_persists_one_run(client, offline_worker, monkeypatch):
    api, factory = client
    calls = []

    def collector(_url, offer_id, **callbacks):
        calls.append(offer_id)
        callbacks['on_navigation_claim']()
        callbacks['on_navigation_confirmed']()
        return CollectionPageResult(offer_id, product(offer_id), None, [])

    monkeypatch.setattr(service, 'collect_1688_product', collector)
    data = payload('https://detail.1688.com/offer/101.html')
    response = api.post('/api/competitors/add-batch', json=data)

    assert response.status_code == 200, response.text
    task = response.json()['task']
    assert task['input_summary']['added'] == 1
    assert task['input_summary']['technical_failed'] == 0
    assert task['page_visits'] == task['attempts_started'] == 1
    assert task['items'][0]['result_code'] == 'added'
    assert len(task['items'][0]['attempts']) == 1
    with factory() as db:
        add_input = db.scalar(select(CollectionAddInput))
        run = db.scalar(select(CollectionRun))
        competitor = db.scalar(select(Competitor))
        snapshot = db.scalar(select(ProductSnapshot))
        assert add_input.batch_id == task['batch_id']
        assert run.collection_batch_item_id == add_input.batch_item_id
        assert run.competitor_id == competitor.id == snapshot.competitor_id
        assert run.status == 'success'
        assert db.scalar(select(OperatingMetricObservation)) is None
    assert len(api.get('/api/competitors').json()) == 1
    assert api.get('/api/collection-runs').json()['total'] == 1

    replay = api.post('/api/competitors/add-batch', json=data)
    assert replay.json()['task_id'] == data['submission_id']
    assert calls == ['101']
    assert api.get('/api/collection-runs').json()['total'] == 1


def test_add_links_maps_page_result_parse_error(client, offline_worker, monkeypatch):
    api, _ = client
    error = CollectionParseError('private parser detail')
    def collector(_url, offer_id, **callbacks):
        callbacks['on_navigation_claim']()
        callbacks['on_navigation_confirmed']()
        return CollectionPageResult(offer_id, None, error, [])
    monkeypatch.setattr(service, 'collect_1688_product', collector)

    task = api.post('/api/competitors/add-batch', json=payload('https://detail.1688.com/offer/101.html')).json()['task']

    assert task['items'][0]['result_code'] == 'technical_failed'
    assert task['items'][0]['error_code'] == 'collection_parse_failed'
    assert task['input_summary']['business_rejected'] == 0
    assert task['page_visits'] == 1


def test_add_links_maps_missing_product_and_error_to_parse_failure(client, offline_worker, monkeypatch):
    api, _ = client
    def collector(_url, offer_id, **callbacks):
        callbacks['on_navigation_claim']()
        callbacks['on_navigation_confirmed']()
        return CollectionPageResult(offer_id, None, None, [])
    monkeypatch.setattr(service, 'collect_1688_product', collector)

    task = api.post('/api/competitors/add-batch', json=payload('https://detail.1688.com/offer/101.html')).json()['task']

    assert task['items'][0]['result_code'] == 'technical_failed'
    assert task['items'][0]['error_code'] == 'collection_parse_failed'
    assert task['input_summary']['business_rejected'] == 0
    assert task['page_visits'] == 1
    assert api.get('/api/competitors').json() == []


@pytest.mark.parametrize('exception,expected_code', [
    (service.LoginRequiredError('private'), '1688_login_required'),
    (service.VerificationRequiredError('private'), '1688_verification_required'),
])
def test_add_links_preserves_login_and_verification_error_mapping(client, offline_worker, monkeypatch, exception, expected_code):
    api, _ = client
    def collector(_url, _offer_id, **callbacks):
        callbacks['on_navigation_claim']()
        callbacks['on_navigation_confirmed']()
        raise exception
    monkeypatch.setattr(service, 'collect_1688_product', collector)

    task = api.post('/api/competitors/add-batch', json=payload('https://detail.1688.com/offer/101.html')).json()['task']

    assert task['items'][0]['result_code'] == 'verification_required'
    assert task['items'][0]['error_code'] == expected_code
    assert task['input_summary']['verification_required'] == 1
    assert task['input_summary']['technical_failed'] == 0
    assert task['page_visits'] == 1


@pytest.mark.parametrize(('page_offer_id', 'product_offer_id'), [('102', '101'), ('101', '102')])
def test_add_links_rejects_page_or_product_offer_id_mismatch(client, offline_worker, monkeypatch, page_offer_id, product_offer_id):
    api, _ = client
    monkeypatch.setattr(service, 'collect_1688_product', lambda _url, _offer_id, **_callbacks: CollectionPageResult(page_offer_id, product(product_offer_id), None, []))

    task = api.post('/api/competitors/add-batch', json=payload('https://detail.1688.com/offer/101.html')).json()['task']

    assert task['items'][0]['result_code'] == 'technical_failed'
    assert task['items'][0]['error_code'] == 'offer_id_mismatch'
    assert task['input_summary']['business_rejected'] == 0
    assert api.get('/api/competitors').json() == []


@pytest.mark.parametrize('missing', ['title', 'shop_name'])
def test_add_links_rejects_page_result_missing_required_product_data(client, offline_worker, monkeypatch, missing):
    api, _ = client
    data = product('101')
    data = data.__class__(**{**data.__dict__, missing: ''})
    monkeypatch.setattr(service, 'collect_1688_product', lambda _url, offer_id, **_callbacks: CollectionPageResult(offer_id, data, None, []))

    task = api.post('/api/competitors/add-batch', json=payload('https://detail.1688.com/offer/101.html')).json()['task']

    expected_result = 'identity_rejected' if missing == 'shop_name' else 'technical_failed'
    expected_error = 'shop_name_unavailable' if missing == 'shop_name' else 'collection_partial_data'
    assert task['items'][0]['result_code'] == expected_result
    assert task['items'][0]['error_code'] == expected_error
    assert task['input_summary']['business_rejected'] == (1 if missing == 'shop_name' else 0)
    assert api.get('/api/competitors').json() == []


@pytest.fixture()
def offline_worker(monkeypatch):
    from app.collection import add_links
    original_config = add_links.batch_config_values
    monkeypatch.setattr(add_links, 'batch_config_values', lambda settings: {**original_config(settings), 'item_interval_seconds': 0, 'batch_rest_seconds': 0})
    class Context:
        pages = []
        def close(self):
            pass
    monkeypatch.setattr(service, 'sync_playwright', lambda: nullcontext(object()))
    monkeypatch.setattr(service, '_launch_context', lambda _: Context())
    monkeypatch.setattr(service, 'move_context_offscreen', lambda _: None)
    monkeypatch.setattr(service, 'collect_1688_product', fake_collector)
    def start(factory, ids, runtime, **kwargs):
        service.run_batch_collection(factory, ids, runtime, **kwargs)
    monkeypatch.setattr(service, 'start_batch_task', start)


def test_add_submission_keeps_invalid_inputs_as_one_task(client):
    api, _ = client
    data = payload('invalid', 'invalid')
    response = api.post('/api/competitors/add-batch', json=data)
    assert response.status_code == 200
    detail = api.get(f"/api/collection-batches/{data['submission_id']}").json()
    assert detail['input_summary']['business_rejected'] == 2
    assert detail['input_summary']['technical_failed'] == 0
    assert detail['planned_products'] == 0
    assert detail['summary']['page_visits'] == 0
    assert len(detail['items']) == 2
    assert api.get('/api/collection-batches?trigger_kind=add_links&anomaly=current').json()['total'] == 0
    assert api.get('/api/collection-batches?trigger_kind=add_links&anomaly=none').json()['total'] == 1


def test_multiple_inputs_persist_one_task_real_runs_rejections_and_single_visits(client, offline_worker):
    api, _ = client
    data = payload('https://detail.1688.com/offer/101.html', 'https://detail.1688.com/offer/102.html', 'https://detail.1688.com/offer/101.html', 'invalid')
    result = api.post('/api/competitors/add-batch', json=data)
    assert result.status_code == 200, result.text
    detail = result.json()['task']
    assert [row['result_code'] for row in detail['items']] == ['added', 'added', 'duplicate_input', 'invalid_url']
    assert detail['input_summary']['added'] == 2
    assert detail['input_summary']['business_rejected'] == 2
    assert detail['input_summary']['technical_failed'] == 0
    assert detail['planned_products'] == detail['page_visits'] == detail['attempts_started'] == 2
    assert detail['completed'] == 2 and detail['remaining'] == 0
    assert len(api.get('/api/competitors').json()) == 2
    assert all(not run['observations'] and run['operating_metrics_status'] == 'not_attempted' for row in detail['items'] for run in row['attempts'])
    replay = api.post('/api/competitors/add-batch', json=data)
    assert replay.json()['task_id'] == data['submission_id']
    assert api.get('/api/collection-batches').json()['total'] == 1
    assert api.get('/api/collection-runs').json()['total'] == 2
    conflict = {**data, 'group_id': 1}
    assert api.post('/api/competitors/add-batch', json=conflict).json()['code'] == 'idempotency_conflict'


def test_final_business_rejection_is_not_a_technical_failure(client, offline_worker, monkeypatch):
    api, factory = client
    original = fake_collector
    def collector(url, offer_id, **callbacks):
        if offer_id == '102':
            from test_collection_api import add_competitor
            add_competitor(factory, offer_id=offer_id)
        return original(url, offer_id, **callbacks)
    monkeypatch.setattr(service, 'collect_1688_product', collector)
    result = api.post('/api/competitors/add-batch', json=payload('https://detail.1688.com/offer/101.html', 'https://detail.1688.com/offer/102.html')).json()['task']
    assert result['input_summary']['added'] == 1
    assert result['input_summary']['business_rejected'] == 1
    assert result['input_summary']['anomaly_inputs'] == 0
    assert result['items'][1]['final_result'] == 'business_rejected'
    assert result['items'][1]['base_result'] == 'not_attempted'
    assert result['completed'] == 2 and result['remaining'] == 0
    assert api.get('/api/collection-batches?anomaly=current').json()['total'] == 0
    assert api.get('/api/collection-batches?anomaly=rejected').json()['total'] == 1


@pytest.mark.parametrize('exception,expected', [(service.CollectionTimeoutError(), 'technical_failed'), (service.VerificationRequiredError(), 'verification_required')])
def test_page_failure_and_verification_leave_no_fake_product_or_run(client, offline_worker, monkeypatch, exception, expected):
    api, _ = client
    def collector(url, offer_id, **callbacks):
        callbacks['on_navigation_claim']()
        callbacks['on_navigation_confirmed']()
        if offer_id == '102':
            raise exception
        return product(offer_id)
    monkeypatch.setattr(service, 'collect_1688_product', collector)
    result = api.post('/api/competitors/add-batch', json=payload(*[f'https://detail.1688.com/offer/{i}.html' for i in (101, 102, 103)])).json()['task']
    assert result['items'][1]['result_code'] == expected
    assert result['items'][1]['competitor_id'] is None
    assert result['items'][1]['attempts'] == []
    assert result['items'][1]['page_visits'] == 1
    assert result['input_summary']['business_rejected'] == 0
    if expected == 'verification_required':
        assert result['items'][2]['result_code'] == 'not_executed'
        assert result['page_visits'] == 2
    else:
        assert result['items'][2]['result_code'] == 'added'
        assert result['input_summary']['technical_failed'] == 1


def test_same_id_pending_conflict_and_different_id_busy_before_commit(client, offline_worker):
    api, _ = client
    data = payload('https://detail.1688.com/offer/101.html')
    entered, release = Event(), Event()
    def block(_mapper, _connection, _batch):
        entered.set()
        assert release.wait(5)
    event.listen(CollectionBatch, 'before_insert', block)
    results = []
    thread = Thread(target=lambda: results.append(api.post('/api/competitors/add-batch', json=data)))
    try:
        thread.start()
        assert entered.wait(3)
        replay = api.post('/api/competitors/add-batch', json=data)
        assert replay.status_code == 202 and replay.json()['accepted'] is False
        conflict = api.post('/api/competitors/add-batch', json={**data, 'group_id': 42})
        assert conflict.status_code == 409 and conflict.json()['code'] == 'idempotency_conflict'
        busy = api.post('/api/competitors/add-batch', json=payload('https://detail.1688.com/offer/101.html'))
        assert busy.status_code == 409 and busy.json()['code'] == 'collection_in_progress'
    finally:
        release.set()
        thread.join(6)
        event.remove(CollectionBatch, 'before_insert', block)
    assert results[0].status_code == 200
    assert api.get('/api/collection-runs').json()['total'] == 1


def test_single_collect_is_batched_and_old_unbatched_history_is_kept(client, monkeypatch):
    from test_collection_api import add_competitor
    api, factory = client
    competitor_id = add_competitor(factory, offer_id='101')
    from datetime import datetime, timezone
    with factory() as db:
        old = CollectionRun(competitor_id=competitor_id, started_at=datetime(2026, 10, 1, tzinfo=timezone.utc), status='success')
        db.add(old)
        db.commit()
        old_id = old.id
    monkeypatch.setattr(service, 'collect_1688_product', fake_collector)
    response = api.post(f'/api/competitors/{competitor_id}/collect')
    assert response.status_code == 200
    batches = api.get('/api/collection-batches?trigger_kind=manual').json()
    assert batches['total'] == 1
    assert batches['items'][0]['trigger_kind'] == 'manual_single'
    detail = api.get('/api/collection-batches/' + batches['items'][0]['task_id']).json()
    assert detail['summary']['page_visits'] == 1
    assert api.get(f'/api/collection-runs/{old_id}').json()['collection_batch_item_id'] is None


def test_legacy_key_replays_success_and_deleted_identity_without_navigation(client, monkeypatch):
    api, _ = client
    calls = []
    def collector(url, offer_id, **callbacks):
        calls.append(offer_id)
        return fake_collector(url, offer_id, **callbacks)
    monkeypatch.setattr(service, 'collect_1688_product', collector)
    key = str(uuid4())
    body = {'url': 'https://detail.1688.com/offer/101.html'}
    first = api.post('/api/competitors', json=body, headers={'Idempotency-Key': key})
    assert first.status_code == 201, first.text
    second = api.post('/api/competitors', json=body, headers={'Idempotency-Key': key})
    assert second.status_code == 201 and second.json()['id'] == first.json()['id']
    assert calls == ['101']
    assert api.delete('/api/competitors/' + str(first.json()['id'])).status_code == 204
    assert api.post('/api/competitors', json=body, headers={'Idempotency-Key': key}).status_code == 410
    detail = api.get('/api/collection-batches/' + key).json()
    assert detail['items'][0]['input_text'] is None
    assert detail['input_summary']['added'] == 1 and detail['page_visits'] == 1


@pytest.mark.parametrize('trigger,anomaly,status', [('add_links','placeholder',422), ('manual','rejected',422), ('scheduled','rejected',422), ('unknown','rejected',200), ('unknown','current',200), ('all','rejected',200), ('add_links','base_failed',200)])
def test_filter_capabilities_and_unknown_compatibility(client, trigger, anomaly, status):
    response = client[0].get(f'/api/collection-batches?trigger_kind={trigger}&anomaly={anomaly}')
    assert response.status_code == status
    if status == 422:
        assert response.json()['code'] == 'incompatible_filter'

@pytest.mark.parametrize('committed', [False, True])
def test_unknown_commit_never_dispatches_and_reconciles_original_identity(client, offline_worker, monkeypatch, committed):
    from sqlalchemy.orm import Session
    api, _ = client
    original = Session.commit
    fail = [True]
    def commit(db):
        admitting = any(isinstance(row, CollectionBatch) for row in db.identity_map.values()) and service.BATCH_RUNTIME.is_busy()
        if admitting and fail[0]:
            fail[0] = False
            if committed:
                original(db)
            raise RuntimeError('commit response lost')
        return original(db)
    monkeypatch.setattr(Session, 'commit', commit)
    data = payload('https://detail.1688.com/offer/101.html')
    response = api.post('/api/competitors/add-batch', json=data)
    assert response.status_code == 503 and response.json()['code'] == 'admission_unknown'
    assert service.BATCH_RUNTIME.is_busy()
    result = api.get('/api/competitors/add-batch/' + data['submission_id'])
    assert result.status_code == (200 if committed else 404), result.text
    assert not service.BATCH_RUNTIME.is_busy()
    if committed:
        assert result.json()['task']['outcome_code'] == 'infrastructure_error'
        assert result.json()['task']['page_visits'] == 0
        assert api.post('/api/competitors/add-batch', json=data).json()['task_id'] == data['submission_id']
        assert api.get('/api/collection-runs').json()['total'] == 0
    else:
        retried = api.post('/api/competitors/add-batch', json=data)
        assert retried.status_code == 200 and retried.json()['task']['input_summary']['added'] == 1


def test_twenty_inputs_end_keeps_rejections_successes_failure_and_fourteen_unexecuted(client, offline_worker, monkeypatch):
    api, _ = client
    def collector(url, offer_id, **callbacks):
        callbacks['on_navigation_claim']()
        callbacks['on_navigation_confirmed']()
        if offer_id == '104':
            from pathlib import Path
            import json
            from fastapi.encoders import jsonable_encoder
            path = Path(__file__).resolve().parents[2] / '.artifacts' / 'v1.3'
            path.mkdir(parents=True, exist_ok=True)
            (path / 'live-progress.json').write_text(json.dumps(jsonable_encoder(service.BATCH_RUNTIME.snapshot()), ensure_ascii=False, indent=2), encoding='utf-8')
            assert service.BATCH_RUNTIME.request_end()
            raise service.CollectionTimeoutError()
        return product(offer_id)
    monkeypatch.setattr(service, 'collect_1688_product', collector)
    data = payload('invalid1', 'invalid2', *[f'https://detail.1688.com/offer/{i}.html' for i in range(101, 119)])
    result = api.post('/api/competitors/add-batch', json=data).json()['task']
    summary = result['input_summary']
    assert {key: summary[key] for key in ('total','processed','added','business_rejected','technical_failed','not_executed','pending','remaining')} == {'total':20, 'processed':6, 'added':3, 'business_rejected':2, 'technical_failed':1, 'not_executed':14, 'pending':0, 'remaining':14}
    assert result['planned_products'] == 18 and result['completed'] == 4 and result['remaining'] == 14
    assert result['page_visits'] == 4 and result['attempts_started'] == 3
    state = api.get('/api/competitors/collect-batch/status').json()
    assert state['status'] == 'stopped' and state['batch_outcome_code'] == 'user_ended'
    assert state['total'] == state['completed'] == state['succeeded'] == state['failed'] == 0
    assert state['input_progress']['processed'] == 6


def test_add_pause_uses_input_position_and_resume_does_not_revisit(client, offline_worker, monkeypatch):
    from time import monotonic, sleep
    api, _ = client
    entered, release = Event(), Event()
    calls, workers = [], []
    def collector(url, offer_id, **callbacks):
        calls.append(offer_id)
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
        return fake_collector(url, offer_id, **callbacks)
    def dispatch(factory, ids, runtime, **kwargs):
        worker = Thread(target=service.run_batch_collection, args=(factory,ids,runtime), kwargs=kwargs)
        workers.append(worker)
        worker.start()
    monkeypatch.setattr(service, 'start_batch_task', dispatch)
    monkeypatch.setattr(service, 'collect_1688_product', collector)
    data = payload('https://detail.1688.com/offer/101.html','https://detail.1688.com/offer/102.html')
    result = api.post('/api/competitors/add-batch', json=data)
    try:
        assert result.status_code == 202 and entered.wait(3)
        paused = api.post('/api/competitors/collect-batch/pause').json()
        assert paused['status'] == 'pausing'
        assert paused['current_competitor_id'] is None and paused['current_input_position'] == 0
        release.set()
        deadline = monotonic()+3
        while service.BATCH_RUNTIME.snapshot()['status'] != 'paused' and monotonic()<deadline:
            sleep(.01)
        assert service.BATCH_RUNTIME.snapshot()['status'] == 'paused'
        assert calls == ['101']
        assert api.post('/api/competitors/collect-batch/resume').status_code == 200
    finally:
        release.set()
        if service.BATCH_RUNTIME.pause_requested():
            service.BATCH_RUNTIME.resume()
        for worker in workers:
            worker.join(5)
    assert calls == ['101','102']
    detail = api.get('/api/collection-batches/' + data['submission_id']).json()
    assert detail['input_summary']['added'] == 2 and detail['page_visits'] == 2


def test_recovery_keeps_rejection_and_unknown_navigation_facts(client):
    from app.collection.add_links import admit_add
    api, factory = client
    task_id = str(uuid4())
    with factory() as db:
        batch_id, _, _ = admit_add(db, task_id, payload('invalid', 'https://detail.1688.com/offer/101.html')['inputs'], None, service.BATCH_RUNTIME)
        row = db.scalar(select(CollectionAddInput).where(CollectionAddInput.batch_id == batch_id, CollectionAddInput.result_code.is_(None)))
        from datetime import datetime, timezone
        row.started_at = row.navigation_claimed_at = datetime.now(timezone.utc)
        db.commit()
    service.BATCH_RUNTIME.finish('collect_failed')
    service.BATCH_RUNTIME.admissions.clear()
    assert service.recover_interrupted_batches(factory) == 1
    assert service.recover_interrupted_batches(factory) == 0
    detail = api.get('/api/collection-batches/' + task_id).json()
    assert detail['input_summary']['business_rejected'] == 1
    assert detail['input_summary']['interrupted'] == 1
    assert detail['page_visits'] == 0 and detail['page_visits_unknown'] == 1
    assert detail['items'][1]['competitor_id'] is None


def test_export_controlled_api_evidence_for_browser_acceptance(client, offline_worker):
    from pathlib import Path
    import json
    from fastapi.encoders import jsonable_encoder
    from test_collection_api import add_competitor
    api, factory = client
    add_competitor(factory, offer_id='104')
    data = payload(*[f'https://detail.1688.com/offer/{i}.html' for i in (101,102,103,104)], 'invalid')
    response = api.post('/api/competitors/add-batch', json=data)
    assert response.status_code == 200
    task = response.json()['task']
    assert task['input_summary']['added'] == 3 and task['input_summary']['business_rejected'] == 2
    path = Path(__file__).resolve().parents[2] / '.artifacts' / 'v1.3'
    path.mkdir(parents=True, exist_ok=True)
    (path / 'api-evidence.json').write_text(json.dumps(jsonable_encoder({'submission': data, 'response': response.json(), 'batch_page': api.get('/api/collection-batches').json()}), ensure_ascii=False, indent=2), encoding='utf-8')
    single = api.post('/api/competitors/1/collect')
    assert single.status_code == 200
    manual = api.get('/api/collection-batches?trigger_kind=manual').json()
    (path / 'single-collect-api.json').write_text(json.dumps({'http_status': single.status_code, 'response': single.json(), 'batches': manual}, ensure_ascii=False, indent=2), encoding='utf-8')


def test_added_product_commit_acknowledgement_loss_does_not_overwrite_success(client, offline_worker, monkeypatch):
    from sqlalchemy.orm import Session
    api, _ = client
    original = Session.commit
    fail = [True]
    def commit(db):
        saving = any(isinstance(row, CollectionRun) for row in db.new)
        original(db)
        if saving and fail[0]:
            fail[0] = False
            raise RuntimeError('saved but response lost')
    monkeypatch.setattr(Session, 'commit', commit)
    response = api.post('/api/competitors/add-batch', json=payload('https://detail.1688.com/offer/101.html'))
    assert response.status_code == 200
    task = response.json()['task']
    assert task['input_summary']['added'] == 1 and task['input_summary']['technical_failed'] == 0
    run_id = task['items'][0]['attempts'][0]['id']
    run = api.get(f'/api/collection-runs/{run_id}').json()
    assert run['navigation_evidence_source'] == 'add_input' and run['navigation_confirmed_at'] is not None


def test_legacy_key_pending_concurrent_replay_and_different_key_busy(client, monkeypatch):
    api, _ = client
    entered, release = Event(), Event()
    calls, results = [], []
    def collector(url, offer_id, **callbacks):
        calls.append(offer_id)
        entered.set()
        assert release.wait(5)
        return fake_collector(url, offer_id, **callbacks)
    monkeypatch.setattr(service, 'collect_1688_product', collector)
    key = str(uuid4())
    data = {'url':'https://detail.1688.com/offer/101.html'}
    worker = Thread(target=lambda: results.append(api.post('/api/competitors', json=data, headers={'Idempotency-Key':key})))
    try:
        worker.start()
        assert entered.wait(3)
        replay = api.post('/api/competitors', json=data, headers={'Idempotency-Key':key})
        assert replay.status_code == 202 and replay.json()['accepted'] is True
        conflict = api.post('/api/competitors', json={'url':'https://detail.1688.com/offer/102.html'}, headers={'Idempotency-Key':key})
        assert conflict.status_code == 409 and conflict.json()['code'] == 'idempotency_conflict'
        busy = api.post('/api/competitors', json=data, headers={'Idempotency-Key':str(uuid4())})
        assert busy.status_code == 409 and busy.json()['code'] == 'collection_in_progress'
    finally:
        release.set()
        worker.join(5)
    assert results[0].status_code == 201
    assert api.post('/api/competitors', json=data, headers={'Idempotency-Key':key}).status_code == 201
    assert calls == ['101']


def test_normal_none_filter_requires_terminal_complete_results(client):
    from test_collection_api import add_competitor
    from datetime import datetime, timezone
    api, factory = client
    competitor_id = add_competitor(factory, offer_id='101')
    with factory() as db:
        for state in ('created','running','not_executed','success'):
            batch = service.create_collection_batch(db, [competitor_id], service.BatchConfig(), trigger_kind='manual_selected')
            item = db.scalar(select(CollectionBatchItem).where(CollectionBatchItem.batch_id == batch.id))
            batch.started_at = datetime.now(timezone.utc)
            if state in {'created','running'}:
                batch.lifecycle_status = state
            else:
                batch.lifecycle_status, batch.outcome_code = 'terminal', 'user_ended' if state == 'not_executed' else 'success'
                item.final_result = 'not_executed' if state == 'not_executed' else 'first_pass_success'
                item.base_result = 'not_attempted' if state == 'not_executed' else 'success'
                item.execution_status = 'not_executed' if state == 'not_executed' else 'completed'
            db.commit()
    result = api.get('/api/collection-batches?anomaly=none').json()
    assert result['total'] == 1
    assert result['items'][0]['outcome_code'] == 'success'


def test_add_list_numeric_counts_agree_with_detail_and_base_failure_filter(client, offline_worker, monkeypatch):
    api, _ = client
    def collector(url, offer_id, **callbacks):
        if offer_id == '104':
            callbacks['on_navigation_claim']()
            callbacks['on_navigation_confirmed']()
            raise service.CollectionTimeoutError()
        return fake_collector(url, offer_id, **callbacks)
    monkeypatch.setattr(service, 'collect_1688_product', collector)
    task = api.post('/api/competitors/add-batch', json=payload(*[f'https://detail.1688.com/offer/{i}.html' for i in (101,102,103,104)])).json()['task']
    row = api.get('/api/collection-batches').json()['items'][0]
    assert type(row['completed']) is int
    assert row['completed'] == task['completed'] == 4
    assert row['remaining'] == task['remaining'] == 0
    filtered = api.get('/api/collection-batches/' + task['task_id'] + '?anomaly=base_failed')
    assert filtered.status_code == 200
    assert [item['result_code'] for item in filtered.json()['items']] == ['technical_failed']
    assert filtered.json()['input_summary'] == task['input_summary']


def test_add_rest_countdown_freezes_on_pause_and_end_prevents_next_visit(client, offline_worker, monkeypatch):
    from time import monotonic, sleep
    from app.collection import add_links
    api, _ = client
    workers, calls = [], []
    original = add_links.batch_config_values
    monkeypatch.setattr(add_links, 'batch_config_values', lambda settings: {**original(settings), 'continuous_collection_count': 1, 'batch_rest_seconds': 3})
    def collector(url, offer_id, **callbacks):
        calls.append(offer_id)
        return fake_collector(url, offer_id, **callbacks)
    def dispatch(factory, ids, runtime, **kwargs):
        worker = Thread(target=service.run_batch_collection, args=(factory,ids,runtime), kwargs=kwargs)
        workers.append(worker)
        worker.start()
    monkeypatch.setattr(service, 'start_batch_task', dispatch)
    monkeypatch.setattr(service, 'collect_1688_product', collector)
    data = payload('https://detail.1688.com/offer/101.html','https://detail.1688.com/offer/102.html')
    try:
        assert api.post('/api/competitors/add-batch', json=data).status_code == 202
        deadline = monotonic()+4
        while monotonic()<deadline:
            state = service.BATCH_RUNTIME.snapshot()
            if state['status'] == 'resting' and state['resting_remaining_seconds'] == 2:
                break
            sleep(.02)
        assert state['resting_remaining_seconds'] == 2
        api.post('/api/competitors/collect-batch/pause')
        sleep(.2)
        frozen = service.BATCH_RUNTIME.snapshot()['resting_remaining_seconds']
        sleep(.3)
        assert service.BATCH_RUNTIME.snapshot()['resting_remaining_seconds'] == frozen
        assert calls == ['101']
        api.post('/api/competitors/collect-batch/resume')
        api.post('/api/competitors/collect-batch/end')
    finally:
        service.BATCH_RUNTIME.request_end()
        for worker in workers:
            worker.join(5)
    assert calls == ['101']
    assert api.get('/api/collection-batches/' + data['submission_id']).json()['input_summary']['not_executed'] == 1
