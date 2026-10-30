from sqlalchemy import select
from sqlalchemy.orm import Session
import io
import zipfile

from app.models import LibrarySimpleEligibilityAudit, LibrarySimpleQuoteVersion
from test_product_library import library


def product(client):
    response = client.post('/api/product-library/products', json={'name': '测试产品', 'model': 'M'})
    assert response.status_code == 201, response.text
    return response.json()


def test_manual_quote_replay_review_and_changed_price(library):
    client, engine = library
    item = product(client)
    base = f"/api/product-library/products/{item['id']}"
    request = {"product_version": item["version"], "supplier": " 供应商 A ", "variant": "红色", "price_text": "12.30", "conditions": "含税，运费另计", "idempotency_key": "manual-1"}
    first = client.post(base + "/manual-quotes", json=request)
    assert first.status_code == 201, first.text
    created = first.json()
    assert client.post(base + "/manual-quotes", json=request).json()["replayed"] is True
    conflict = client.post(base + "/manual-quotes", json={**request, "conditions": "其他条件"})
    assert conflict.status_code == 409
    review = client.post(base + f"/quotes/{created['quote_version_id']}/review", json={"product_version": item["version"] + 1, "status": "eligible", "reason": "核对原始出厂报价及每件单位", "source_id": created['source_id']})
    assert review.status_code == 200, review.text
    changed = client.post(base + "/manual-quotes", json={**request, "product_version": review.json()["product_version"], "price_text": "13", "idempotency_key": "manual-2"})
    assert changed.status_code == 201, changed.text
    with Session(engine) as db:
        versions = db.scalars(select(LibrarySimpleQuoteVersion).order_by(LibrarySimpleQuoteVersion.id)).all()
        assert [(v.amount_cents, v.eligibility, v.is_current) for v in versions] == [(1230, "eligible", False), (1300, "pending", True)]
        assert len(db.scalars(select(LibrarySimpleEligibilityAudit)).all()) == 1


def test_manual_non_wholesale_price_is_rejected(library):
    client, _ = library
    item = product(client)
    request = {"product_version": item["version"], "supplier": "A", "variant": None, "price_text": "一件代发价：12", "conditions": "不含运费", "idempotency_key": "k"}
    response = client.post(f"/api/product-library/products/{item['id']}/manual-quotes", json=request)
    assert response.status_code == 422


def test_archive_and_restore_require_new_eligibility_review(library):
    client, engine = library
    item = product(client)
    base = f"/api/product-library/products/{item['id']}"
    request = {"product_version": item["version"], "supplier": "A", "variant": None, "price_text": "12", "conditions": "含税不含运费", "idempotency_key": "archive-test"}
    quote = client.post(base + "/manual-quotes", json=request).json()
    review = client.post(base + f"/quotes/{quote['quote_version_id']}/review", json={"product_version": item["version"] + 1, "status": "eligible", "reason": "已核对出厂报价", "source_id": quote['source_id']}).json()
    assert client.request("DELETE", base, json={"version": review["product_version"]}).status_code == 204
    assert client.get(base).status_code == 404
    assert client.get("/api/product-library/products").json()["total"] == 0
    restored = client.post(base + "/restore", json={"version": review["product_version"] + 1})
    assert restored.status_code == 200, restored.text
    with Session(engine) as db:
        assert db.get(LibrarySimpleQuoteVersion, quote["quote_version_id"]).eligibility == "pending"
        assert len(db.scalars(select(LibrarySimpleEligibilityAudit)).all()) == 2


def test_customer_quote_requires_eligible_current_version_and_confirmed_source(library):
    client, _ = library
    item = product(client)
    base = f"/api/product-library/products/{item['id']}"
    request = {"product_version": item["version"], "supplier": "A", "variant": None, "price_text": "12", "conditions": "含税，运费另计", "idempotency_key": "quote-test"}
    quote = client.post(base + "/manual-quotes", json=request).json()
    selection = {"quote_version_id": quote['quote_version_id'], "source_id": quote['source_id'], "supplier": "A", "variant": None, "final_conditions": "含税，运费另计", "rules_confirmed": True}
    preview = {"scope": "selected", "items": [{"id": item['id'], "version": item['version'] + 1}], "include_unquoted": True, "rules": {'tax_mode': 'included'}, "selections": {str(item['id']): selection}, "overrides": {str(item['id']): "20"}}
    url = "/api/product-library/customer-quotations/preview"
    assert client.post(url, json=preview).status_code == 409
    reviewed = client.post(base + f"/quotes/{quote['quote_version_id']}/review", json={"product_version": item['version'] + 1, "status": "eligible", "reason": "核对出厂价", "source_id": quote['source_id']}).json()
    preview['items'][0]['version'] = reviewed['product_version']
    unconfirmed = client.post(url, json=preview).json()
    assert unconfirmed['rows'][0]['final_price'] is None
    approved = client.post(url, json={**preview, "conditions_confirmed_ids": [item['id']]}).json()
    assert approved['rows'][0]['final_price'] == '20.00'
    assert approved['snapshots'][0]['source_id'] == quote['source_id']
    assert approved['snapshots'][0]['source_conditions'] == '含税，运费另计'
    assert approved['snapshots'][0]['amount_cents'] == 1200
    assert client.post(url, json={**preview, 'rules': {'tax_mode': 'excluded'}, 'conditions_confirmed_ids': [item['id']]}).status_code == 422
    assert client.post(url, json={**preview, "selections": {}, "conditions_confirmed_ids": [item['id']]}).json()['rows'][0]['final_price'] is None
    assert client.post(url, json={**preview, "selections": {str(item['id']): {**selection, "source_id": 999}}}).status_code == 409
    below_preview = {**preview, 'overrides': {str(item['id']): '10'}, 'conditions_confirmed_ids': [item['id']]}
    below = client.post(url, json=below_preview).json()
    export = {key: below[key] for key in ('items', 'rules', 'digest', 'moq', 'note', 'selections', 'conditions_confirmed_ids')}
    export.update(overrides=below_preview['overrides'], confirmed_risk_ids=[], confirmed_all_text=True)
    assert client.post('/api/product-library/customer-quotations/export', json=export).status_code == 422
    file = client.post('/api/product-library/customer-quotations/export', json={**export, 'confirmed_below_cost_ids': [item['id']]})
    assert file.status_code == 200
    with zipfile.ZipFile(io.BytesIO(file.content)) as archive:
        contents = b''.join(archive.read(name) for name in archive.namelist())
        assert '含税，运费另计'.encode() not in contents


def test_pending_same_price_sources_are_not_all_promoted_by_one_review(library):
    client, _ = library
    item = product(client)
    base = f"/api/product-library/products/{item['id']}"
    request = {'product_version': item['version'], 'supplier': 'A', 'variant': None, 'price_text': '12', 'conditions': '条件一', 'idempotency_key': 'one'}
    first = client.post(base + '/manual-quotes', json=request).json()
    second = client.post(base + '/manual-quotes', json={**request, 'product_version': item['version'] + 1, 'conditions': '条件二', 'idempotency_key': 'two'}).json()
    assert first['quote_version_id'] == second['quote_version_id']
    response = client.post(base + f"/quotes/{first['quote_version_id']}/review", json={'product_version': item['version'] + 2, 'status': 'eligible', 'reason': '核对来源一', 'source_id': first['source_id']})
    assert response.status_code == 200, response.text
    detail = client.get(base).json()
    current = next(q for q in detail['quotes'] if q['is_current'])
    assert current['eligibility'] == 'eligible'
    assert current['source_ids'] == [first['source_id']]
    assert len(detail['quotes']) == 2


def test_same_price_manual_source_requires_semantic_review(library):
    client, _ = library
    item = product(client)
    base = f"/api/product-library/products/{item['id']}"
    request = {'product_version': item['version'], 'supplier': 'A', 'variant': None, 'price_text': '12', 'conditions': '含税', 'idempotency_key': 'one'}
    first = client.post(base + '/manual-quotes', json=request).json()
    reviewed = client.post(base + f"/quotes/{first['quote_version_id']}/review", json={'product_version': item['version'] + 1, 'status': 'eligible', 'reason': '核对出厂价', 'source_id': first['source_id']}).json()
    second = client.post(base + '/manual-quotes', json={**request, 'product_version': reviewed['product_version'], 'conditions': '零售价说明', 'idempotency_key': 'two'}).json()
    assert second['requires_source_confirmation']
    detail = client.get(base).json()
    assert detail['quotes'][0]['source_ids'] == [first['source_id']]
    result = client.post(base + f"/quotes/{first['quote_version_id']}/confirm-source", json={'product_version': detail['version'], 'source_id': second['source_id'], 'reason': '核对'})
    assert result.status_code == 422
    assert client.get(base).json()['quotes'][0]['source_ids'] == [first['source_id']]


def test_archiving_only_evidence_revokes_quote_eligibility(library):
    client, _ = library
    item = product(client)
    base = f"/api/product-library/products/{item['id']}"
    request = {'product_version': item['version'], 'supplier': 'A', 'variant': None, 'price_text': '12', 'conditions': '含税', 'idempotency_key': 'one'}
    quote = client.post(base + '/manual-quotes', json=request).json()
    reviewed = client.post(base + f"/quotes/{quote['quote_version_id']}/review", json={'product_version': item['version'] + 1, 'status': 'eligible', 'reason': '核对出厂价', 'source_id': quote['source_id']}).json()
    response = client.request('DELETE', base + f"/sources/{quote['source_id']}", json={'product_version': reviewed['product_version'], 'source_version': 1})
    assert response.status_code == 204, response.text
    detail = client.get(base).json()
    assert detail['sources'][0]['archived'] is True
    assert detail['quotes'][0]['eligibility'] == 'pending'


def test_stopped_quote_keeps_history_and_next_version(library):
    client, _ = library
    item = product(client)
    base = f"/api/product-library/products/{item['id']}"
    request = {'product_version': item['version'], 'supplier': 'A', 'variant': None, 'price_text': '12', 'conditions': '含税', 'idempotency_key': 'one'}
    first = client.post(base + '/manual-quotes', json=request).json()
    assert client.request('DELETE', base + f"/quotes/{first['quote_version_id']}", json={'product_version': item['version'] + 1}).status_code == 204
    second = client.post(base + '/manual-quotes', json={**request, 'product_version': item['version'] + 2, 'idempotency_key': 'two'})
    assert second.status_code == 201, second.text
    quotes = client.get(base).json()['quotes']
    assert [(q['version_number'], q['is_current']) for q in quotes] == [(1, False), (2, True)]


def test_other_product_source_cannot_be_used_and_snapshot_expires(library):
    client, _ = library
    first = product(client)
    other = client.post('/api/product-library/products', json={'name': '另一款', 'model': 'N'}).json()
    def add(item, key):
        return client.post(f"/api/product-library/products/{item['id']}/manual-quotes", json={'product_version': item['version'], 'supplier': 'A', 'variant': None, 'price_text': '12', 'conditions': '含税', 'idempotency_key': key}).json()
    q1, q2 = add(first, 'first'), add(other, 'second')
    base = f"/api/product-library/products/{first['id']}"
    review = client.post(base + f"/quotes/{q1['quote_version_id']}/review", json={'product_version': first['version'] + 1, 'status': 'eligible', 'reason': '已核对', 'source_id': q1['source_id']}).json()
    selection = {'quote_version_id': q1['quote_version_id'], 'source_id': q1['source_id'], 'supplier': 'A', 'variant': None, 'final_conditions': '含税，运费另计', 'rules_confirmed': True}
    request = {'scope': 'selected', 'items': [{'id': first['id'], 'version': review['product_version']}], 'include_unquoted': True, 'rules': {'tax_mode': 'included'}, 'selections': {str(first['id']): selection}, 'conditions_confirmed_ids': [first['id']]}
    url = '/api/product-library/customer-quotations/preview'
    assert client.post(url, json={**request, 'selections': {str(first['id']): {**selection, 'source_id': q2['source_id']}}}).status_code == 409
    preview = client.post(url, json=request).json()
    assert preview['rows'][0]['final_price'] == '12.00'
    assert client.request('DELETE', base + f"/sources/{q1['source_id']}", json={'product_version': review['product_version'], 'source_version': 1}).status_code == 204
    export = {key: preview[key] for key in ('items', 'rules', 'digest', 'moq', 'note', 'selections', 'conditions_confirmed_ids')}
    export.update(overrides={}, confirmed_risk_ids=[], confirmed_all_text=True)
    assert client.post('/api/product-library/customer-quotations/export', json=export).status_code == 409


def test_product_identity_and_control_price_do_not_depend_on_supplier(library):
    client, engine = library
    response = client.post('/api/product-library/products', json={'name': '灯', 'model': '001', 'parameters': '参数原文', 'control_price': '平台控价 29'})
    assert response.status_code == 201, response.text
    item = response.json()
    assert item['control_price'] == '平台控价 29'
    with engine.connect() as connection:
        assert connection.exec_driver_sql('SELECT manufacturer_name, wholesale_price_cents FROM library_products').one() == (None, None)
    duplicate = client.post('/api/product-library/products', json={'name': '灯', 'model': '001'})
    assert duplicate.status_code == 409
    unquoted = client.post('/api/product-library/customer-quotations/preview', json={'scope': 'selected', 'items': [{'id': item['id'], 'version': item['version']}], 'include_unquoted': True, 'overrides': {str(item['id']): '100'}})
    assert unquoted.json()['rows'][0]['final_price'] is None
