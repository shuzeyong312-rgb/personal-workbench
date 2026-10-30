import copy
import io
import zipfile

import pytest
from openpyxl import Workbook, load_workbook
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.models import LibraryImport, LibraryProduct
from app.product_library_v2_import import SHEETS
from test_product_library import library, product, preview as preview_v1, confirm as confirm_v1

BASE = '/api/product-library'


def workbook(tables=None):
    wb=Workbook()
    wb.remove(wb.active)
    for sheet,headers in SHEETS.items():
        ws=wb.create_sheet(sheet)
        ws.append(headers)
        for row in (tables or {}).get(sheet,[]):
            ws.append(row)
    output=io.BytesIO()
    wb.save(output)
    return output.getvalue()


def upload(client,tables,company='资料公司'):
    return client.post(BASE+'/imports/preview',params={'manufacturer_name':company},content=workbook(tables))


def plan(preview, overrides=None):
    choices=[]
    for row in preview['rows']:
        choice=dict(row_key=row['row_key'],action=row['default_action'])
        choice.update((overrides or {}).get((row['row_key']['sheet'],row['row_key']['temp_id']),{}))
        if choice['action'] in ('update_main','use_existing','append_source','update','reuse'):
            choice.update(target_id=row['target_id'],target_version=row['target_version'])
        choices.append(choice)
    return dict(decisions=choices,confirmed_attachments_not_imported=True)


def confirm(client,preview,payload=None):
    return client.post(BASE+f"/imports/{preview['import_id']}/confirm",json=payload or plan(preview))


def tables():
    return {
        '产品数据':[['P','H8','暖手袋',None,'原文参数']],
        '规格款式':[['V1','P','5000mAh'],['V2','P','10000mAh']],
        '资料索引':[['S','P','报价公司',None,'原件.pdf','2','2026-10-01','quote','摘录']],
        '价格明细':[
            ['A','P','V1','批发价',None,'12.30','CNY','件','20','件','excluded','excluded',None,None,'2026-10-01','S','false','20件起'],
            ['B','P','V1','一件代发价',None,'15','CNY','件',None,None,None,None,None,None,None,'S'],
            ['C','P','V2','批发价',None,'20','CNY','件',None,None,None,None,None,None,None,'S'],
            ['D','P','V2','一件代发价',None,'25','CNY','件',None,None,None,None,None,None,None,'S'],
        ],
        '参数明细':[['P','V1','S','供电/电池','容量','5000','mAh',None,'原文5000']],
    }


def detail(client,product_id=1):
    response=client.get(BASE+f'/products/{product_id}')
    assert response.status_code==200,response.text
    return response.json()


def upload_simple(client, rows, company='资料公司'):
    from test_product_library_simple_import import workbook as simple_workbook, HEADERS
    response = client.post(BASE + '/imports/preview', params={'manufacturer_name': company}, headers={'X-Filename': 'simple.xlsx'}, content=simple_workbook('产品清单', HEADERS, rows))
    assert response.status_code == 201, response.text
    return response.json()


def confirm_simple(client, data, choices=None):
    decisions = choices if choices is not None else [{'row_number': row['row_number'], 'action': 'apply'} for row in data['rows']]
    return client.post(BASE + f"/imports/{data['import_id']}/confirm", json={'confirmed_attachments_not_imported': True, 'decisions': decisions})


def test_five_sheet_import_is_retired_without_writes(library):
    client,engine=library
    response=upload(client,tables())
    assert response.status_code == 400
    with Session(engine) as db:
        assert db.query(LibraryProduct).count()==0
        assert db.query(LibraryImport).count()==0


def test_cross_source_does_not_overwrite_main_or_default(library):
    client,_=library
    old=client.post(BASE+'/products',json={'model':'X','name':'产品','parameters':'旧参数'}).json()
    source=client.post(BASE+f"/products/{old['id']}/manual-quotes",json={'product_version':old['version'],'supplier':'厂家','variant':None,'price_text':'9.00','conditions':'未税','idempotency_key':'cross-source'}).json()
    assert client.post(BASE+f"/products/{old['id']}/quotes/{source['quote_version_id']}/review",json={'product_version':old['version']+1,'source_id':source['source_id'],'status':'eligible','reason':'核对出厂价'}).status_code==200
    old=detail(client,old['id'])
    data=upload_simple(client,[[None,'X','产品','新参数','2.00']])
    assert confirm_simple(client,data).status_code==200
    p=detail(client,old['id'])
    assert p['manufacturer_name'] is None and p['parameters']=='旧参数' and p['wholesale_price'] is None
    assert {q['amount_cents'] for q in p['quotes']} == {900,200}
    assert p['sources'][-1]['raw_values']['values']['产品参数']=='新参数'
    assert p['version']==old['version']+1
    assert client.get(BASE+'/products',params={'manufacturer':'资料公司'}).json()['total']==1


@pytest.mark.parametrize('kind,mutation',[
    ('orphan',lambda t:t['价格明细'][0].__setitem__(2,'missing')),
    ('duplicate_id',lambda t:t['规格款式'][1].__setitem__(0,'V1')),
    ('cross_product',lambda t:t['产品数据'].append(['Q','Q','另一个'])),
])
def test_structural_references(library,kind,mutation):
    client,_=library
    t=tables();mutation(t)
    if kind=='cross_product':
        t['规格款式'][0][1]='Q'
    response=upload(client,t)
    assert response.status_code==400,response.text


def test_skipped_row_does_not_insert_product_or_source(library):
    client,_=library
    data=upload_simple(client,[[None,'M','产品',None,'12']])
    assert confirm_simple(client,data,[{'row_number':2,'action':'skip'}]).status_code==200
    assert client.get(BASE+'/products').json()['total']==0


def test_import_failure_rolls_back_all_relations_and_receipt(library):
    client,engine=library
    data=upload_simple(client,[[None,'M','产品',None,'12']])
    def fail(connection,cursor,statement,parameters,context,executemany):
        if statement.startswith('INSERT INTO library_simple_quote_versions'):
            from sqlalchemy.exc import OperationalError
            raise OperationalError(statement,parameters,Exception('injected'))
    event.listen(engine,'before_cursor_execute',fail)
    try:
        assert confirm_simple(client,data).json()['code']=='import_save_failed'
    finally:
        event.remove(engine,'before_cursor_execute',fail)
    with Session(engine) as db:
        assert db.query(LibraryProduct).count()==0
        assert db.get(LibraryImport,data['import_id']).status=='ready'
    assert confirm_simple(client,data).status_code==200


def test_conflicting_text_parameters_preserve_both_source_facts(library):
    client,_=library
    first=upload_simple(client,[[None,'GS','风扇','包装尺寸：10cm']],'供应商甲')
    assert confirm_simple(client,first).status_code==200
    second=upload_simple(client,[[None,'GS','风扇','包装尺寸：12cm']],'供应商乙')
    assert second['rows'][0]['differences']['parameters']=={'current':'包装尺寸：10cm','incoming':'包装尺寸：12cm'}
    assert confirm_simple(client,second).status_code==200
    saved=detail(client)
    assert saved['parameters']=='包装尺寸：10cm'
    assert {s['raw_values']['values']['产品参数'] for s in saved['sources']}=={'包装尺寸：10cm','包装尺寸：12cm'}


def test_price_versions_and_source_archiving_preserve_history(library):
    client,_=library
    first=upload_simple(client,[[None,'M','产品',None,'12.30']]);assert confirm_simple(client,first).status_code==200
    p=detail(client);source=p['sources'][0]
    second=upload_simple(client,[[None,'M','产品',None,'15.00']])
    assert confirm_simple(client,second,[{'row_number':2,'action':'apply','price_decisions':{'':'update'}}]).status_code==200
    p=detail(client)
    assert [(q['amount_cents'],q['is_current']) for q in p['quotes']]==[(1230,False),(1500,True)]
    assert p['wholesale_price'] is None
    response=client.request('DELETE',BASE+f"/products/{p['id']}/sources/{source['id']}",json={'product_version':p['version'],'source_version':source['version']})
    assert response.status_code==204
    assert detail(client)['sources'][0]['archived'] is True and len(detail(client)['quotes'])==2


def test_quote_explicit_selection_conditions_and_no_internal_xlsx(library):
    client,_=library
    data=upload_simple(client,[[None,'H8','暖手袋','原文参数','5000mAh：12.30；10000mAh：20','59',None,'未税，运费另计']],'INTERNAL_SENTINEL_COMPANY')
    assert confirm_simple(client,data).status_code==200
    p=detail(client);cost=p['quotes'][0];source=p['sources'][0]
    base=dict(scope='selected',items=[{'id':p['id'],'version':p['version']}],include_unquoted=True)
    invalid=client.post(BASE+'/customer-quotations/preview',json={**base,'selections':{'1':{'price_id':59}}})
    assert invalid.status_code==422
    selections={'1':{'quote_version_id':cost['id'],'source_id':source['id'],'supplier':'INTERNAL_SENTINEL_COMPANY','variant':'5000mAh','final_conditions':'未税，运费另计','rules_confirmed':True}}
    q=client.post(BASE+'/customer-quotations/preview',json={**base,'selections':selections}).json()
    assert q['rows'][0]['error'] and q['rows'][0]['final_price'] is None
    q=client.post(BASE+'/customer-quotations/preview',json={**base,'selections':selections,'overrides':{'1':'30'}}).json()
    assert q['rows'][0]['error'] and q['rows'][0]['final_price'] is None
    q=client.post(BASE+'/customer-quotations/preview',json={**base,'selections':selections,'conditions_confirmed_ids':[1]}).json()
    assert q['rows'][0]['final_price']=='12.30' and '5000mAh' in q['rows'][0]['name']
    payload={k:q[k] for k in ('items','rules','digest','moq','note','selections','conditions_confirmed_ids')}
    payload.update(overrides={},confirmed_risk_ids=[],confirmed_all_text=True)
    response=client.post(BASE+'/customer-quotations/export',json=payload)
    assert response.status_code==200,response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert all(b'INTERNAL_SENTINEL' not in archive.read(name) for name in archive.namelist())
    ws=load_workbook(io.BytesIO(response.content)).active
    assert ws.max_column==7 and '5000mAh' in ws.cell(2,2).value


@pytest.mark.parametrize('amount,expected_cents',[
    ('0', 0), (None, None), ('1.234美元/箱', None), ('1.234元/件', None),
    ('NaN', None), ('1e3美元/件', None), ('12/件', None), ('12元/箱', None),
    ('12 BAD/件', None), ('-1', None),
])
def test_price_value_boundaries(library,amount,expected_cents):
    from test_product_library_simple_import import workbook as simple_workbook, HEADERS
    client,_=library
    data=client.post(BASE+'/imports/preview',params={'manufacturer_name':'资料公司'},headers={'X-Filename':'test.xlsx'},content=simple_workbook('产品清单',HEADERS,[[None,'M','产品',None,amount]])).json()
    row=data['rows'][0]
    assert not row['errors']
    response=client.post(BASE+f"/imports/{data['import_id']}/confirm",json={'confirmed_attachments_not_imported':True,'decisions':[{'row_number':2,'action':'apply'}]})
    assert response.status_code==200,response.text
    p=detail(client)
    assert len(p['quotes']) == (1 if expected_cents is not None else 0)
    if expected_cents is not None:
        assert p['quotes'][0]['amount_cents'] == expected_cents and p['quotes'][0]['eligibility'] == 'eligible'
    else:
        assert p['sources'][0]['price_text'] == amount


def test_same_price_different_files_add_evidence_without_duplicate_quote(library):
    client,_=library
    data=upload_simple(client,[[None,'H8','暖手袋','原文','蓝：12']]);assert confirm_simple(client,data).status_code==200
    p=detail(client)
    data=upload_simple(client,[[None,'H8','暖手袋','原文','蓝：12',None,None,'不同条件']])
    assert confirm_simple(client,data).status_code==200
    changed=detail(client)
    assert changed['version']==p['version']+1
    assert len(changed['quotes'])==1 and len(changed['quotes'][0]['source_ids'])==2


def test_changed_related_record_invalidates_import_and_quote(library):
    client,_=library
    rows=[[None,'M','产品','参数','12',None,None,'未税，运费另计']]
    data=upload_simple(client,rows);assert confirm_simple(client,data).status_code==200
    p=detail(client)
    ready=upload_simple(client,rows)
    source=p['sources'][0]
    selection={'quote_version_id':p['quotes'][0]['id'],'source_id':source['id'],'supplier':'资料公司','variant':None,'final_conditions':'未税，运费另计','rules_confirmed':True}
    q=client.post(BASE+'/customer-quotations/preview',json={'scope':'selected','items':[{'id':p['id'],'version':p['version']}],'include_unquoted':True,'selections':{str(p['id']):selection},'conditions_confirmed_ids':[p['id']]}).json()
    assert client.request('DELETE',BASE+f"/products/{p['id']}/sources/{source['id']}",json={'product_version':p['version'],'source_version':source['version']}).status_code==204
    assert confirm_simple(client,ready).json()['code']=='import_stale'
    payload={key:q[key] for key in ('items','rules','digest','moq','note','selections','conditions_confirmed_ids')}
    payload.update(overrides={},confirmed_risk_ids=[],confirmed_all_text=True)
    assert client.post(BASE+'/customer-quotations/export',json=payload).json()['code']=='quotation_stale'


def test_same_receipt_concurrency_and_reordered_idempotent_replay(library):
    from concurrent.futures import ThreadPoolExecutor
    client,_=library
    data=upload_simple(client,[[None,'M1','产品1',None,'12'],[None,'M2','产品2',None,'20']])
    choices=[{'row_number':2,'action':'apply'},{'row_number':3,'action':'apply'}]
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda _:confirm_simple(client,data,choices),range(2)))
    assert [response.status_code for response in responses]==[200,200]
    assert responses[0].json()==responses[1].json()
    assert confirm_simple(client,data,list(reversed(choices))).json()==responses[0].json()
    assert len(detail(client)['quotes'])==1 and client.get(BASE+'/products').json()['total']==2


def test_cross_product_foreign_keys_and_product_archive_preserves_history(library):
    from sqlalchemy.exc import IntegrityError
    from app.models import LibrarySimpleQuoteEvidence
    client,engine=library
    a=client.post(BASE+'/products',json={'model':'A','name':'产品A'}).json()
    b=client.post(BASE+'/products',json={'model':'B','name':'产品B'}).json()
    def add(item, request_key):
        return client.post(BASE+f"/products/{item['id']}/manual-quotes",json={'product_version':item['version'],'supplier':'A','variant':None,'price_text':'12','conditions':'未税','idempotency_key':request_key}).json()
    first,second=add(a,'a'),add(b,'b')
    current=detail(client,a['id'])
    key=current['quotes'][0]['key_id']
    with Session(engine) as db:
        db.add(LibrarySimpleQuoteEvidence(quote_version_id=first['quote_version_id'],quote_key_id=key,product_id=a['id'],source_id=second['source_id']))
        with pytest.raises(IntegrityError):
            db.commit()
    assert client.request('DELETE',BASE+f"/products/{a['id']}",json={'version':current['version']}).status_code==204
    with engine.connect() as connection:
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all()==[]
        assert connection.exec_driver_sql('SELECT COUNT(*) FROM library_simple_quote_versions').scalar()==2
        assert connection.exec_driver_sql('SELECT COUNT(*) FROM library_simple_quote_evidence').scalar()==2


def test_generic_price_semantics_modes_and_no_quote(library):
    client,_=library
    rows=[[None,'GS008','示例1',None,'出货价：26','零售控价59'],[None,'DM82','示例2',None,None,'阿里22.9；C端39.9'],[None,'S17','无报价'],[None,'W01','多模式','自然风5W；强风10W']]
    data=upload_simple(client,rows);response=confirm_simple(client,data)
    assert response.status_code==200,response.text
    assert not any(r['errors'] for r in data['rows'])
    assert detail(client,1)['quotes']==[] and detail(client,1)['sources'][0]['price_text']=='出货价：26'
    assert detail(client,2)['control_price']=='阿里22.9；C端39.9' and detail(client,2)['quotes']==[]
    assert detail(client,3)['quotes']==[] and detail(client,3)['wholesale_price'] is None
    assert detail(client,4)['parameters']=='自然风5W；强风10W'


def test_legacy_default_unknown_conditions_require_confirmation(library):
    client,_=library
    data=preview_v1(client,[['M','产品',None,None,'12.30']]).json()
    assert confirm_simple(client,data).status_code==200
    p=detail(client);quote=p['quotes'][0];source=p['sources'][0]
    assert quote['eligibility']=='pending' and p['wholesale_price'] is None
    selection={'quote_version_id':quote['id'],'source_id':source['id'],'supplier':'厂家','variant':None,'final_conditions':'未税，运费另计','rules_confirmed':True}
    payload={'scope':'selected','items':[{'id':p['id'],'version':p['version']}],'include_unquoted':True,'selections':{str(p['id']):selection},'conditions_confirmed_ids':[p['id']]}
    assert client.post(BASE+'/customer-quotations/preview',json=payload).status_code==409
    reviewed=client.post(BASE+f"/products/{p['id']}/quotes/{quote['id']}/review",json={'product_version':p['version'],'source_id':source['id'],'status':'eligible','reason':'核对出厂价'}).json()
    payload['items'][0]['version']=reviewed['product_version']
    assert client.post(BASE+'/customer-quotations/preview',json=payload).json()['rows'][0]['final_price']=='12.30'


def test_product_edit_cannot_override_price_or_historical_manufacturer(library):
    client,_=library
    ready=upload_simple(client,[[None,'X','产品',None,'2.00']]);assert confirm_simple(client,ready).status_code==200
    p=detail(client)
    payload={field:p[field] for field in ('category','model','name','parameters','control_price','selling_points','version')}
    assert client.put(BASE+'/products/1',json={**payload,'wholesale_price':'7.00'}).status_code==422
    assert client.put(BASE+'/products/1',json={**payload,'manufacturer_name':'虚构厂家'}).status_code==422
    assert detail(client)['quotes'][0]['amount_cents']==200


def test_v1_media_warning_requires_confirmation_and_receipt_records_it(library):
    from test_product_library import workbook as v1_workbook
    client,_=library
    output=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(v1_workbook([['M','产品']])) ) as original, zipfile.ZipFile(output,'w') as result:
        for entry in original.infolist():
            result.writestr(entry,original.read(entry.filename))
        result.writestr('xl/media/unused.png',b'not-imported-image')
    ready=client.post(BASE+'/imports/preview',params={'manufacturer_name':'公司'},content=output.getvalue()).json()
    assert ready['attachment_warning']
    assert client.post(BASE+f"/imports/{ready['import_id']}/confirm",json={'decisions':[{'row_number':2,'action':'apply'}]}).status_code==422
    payload={'decisions':[{'row_number':2,'action':'apply'}],'confirmed_attachments_not_imported':True}
    response=client.post(BASE+f"/imports/{ready['import_id']}/confirm",json=payload)
    assert response.status_code==200,response.text
    assert response.json()['attachments_not_imported'] is True


def test_supplier_is_required_and_workbook_filename_is_recorded(library):
    client,_=library
    assert client.post(BASE+'/imports/preview',params={'manufacturer_name':'公司'},content=workbook(),headers={'X-Filename':'a'*501+'.xlsx'}).status_code==422
    from test_product_library_simple_import import workbook as simple_workbook, HEADERS
    content=simple_workbook('产品清单',HEADERS,[[None,'X','资料']])
    assert client.post(BASE+'/imports/preview',params={'manufacturer_name':''},headers={'X-Filename':'products.xlsx'},content=content).status_code==422
    data=client.post(BASE+'/imports/preview',params={'manufacturer_name':'公司'},headers={'X-Filename':'products.xlsx'},content=content).json()
    assert confirm_simple(client,data).status_code==200
    source=detail(client)['sources'][0]
    assert source['file_name']=='products.xlsx' and source['sheet_name']=='产品清单' and source['row_number']==2


def test_stopping_variant_quote_preserves_product_parameters_and_source(library):
    client,_=library
    data=upload_simple(client,[[None,'X','资料','尺寸：10cm','蓝：12']])
    assert confirm_simple(client,data).status_code==200
    p=detail(client);quote=p['quotes'][0]
    response=client.request('DELETE',BASE+f"/products/{p['id']}/quotes/{quote['id']}",json={'product_version':p['version']})
    assert response.status_code==204
    saved=detail(client)
    assert saved['parameters']=='尺寸：10cm' and saved['sources'][0]['price_text']=='蓝：12'
    assert saved['quotes'][0]['variant']=='蓝' and not saved['quotes'][0]['is_current']


def test_long_source_text_remains_intact_when_source_is_archived(library):
    client,_=library
    ready=preview_v1(client,[['M','资料','参'*10000,'卖'*10000]]).json()
    assert confirm_simple(client,ready).status_code==200
    p=detail(client);source=p['sources'][0]
    assert source['raw_values']['values']['parameters']=='参'*10000
    assert source['raw_values']['values']['selling_points']=='卖'*10000
    response=client.request('DELETE',BASE+f"/products/{p['id']}/sources/{source['id']}",json={'product_version':p['version'],'source_version':source['version']})
    assert response.status_code==204,response.text
    saved=detail(client)['sources'][0]
    assert saved['archived'] and saved['raw_values']==source['raw_values']


def test_new_product_uses_single_explicit_source_when_batch_company_unknown(library):
    client,_=library
    data=upload_simple(client,[[None,'X','资料',None,None,None,None,'来源条件']],'明确来源公司')
    response=confirm_simple(client,data)
    assert response.status_code==200,response.text
    p=detail(client)
    assert p['manufacturer_name'] is None
    assert {source['supplier_name'] for source in p['sources']}=={'明确来源公司'}


def test_mixed_workbook_resolves_first_company_per_product(library):
    client,_=library
    for company,model,name in [('公司甲','X','产品甲'),('公司乙','Y','产品乙')]:
        assert confirm_simple(client,upload_simple(client,[[None,model,name]],company)).status_code==200
    assert detail(client,1)['sources'][0]['supplier_name']=='公司甲'
    assert detail(client,2)['sources'][0]['supplier_name']=='公司乙'


def test_existing_product_retains_full_main_row_with_explicit_source(library):
    client,engine=library
    old=client.post(BASE+'/products',json={'model':'X','name':'产品','parameters':'旧参数','selling_points':'旧卖点'}).json()
    incoming=[[None,'X','产品','完整新参数\n第二段',None,None,'完整新卖点\n第二项','新价格条件备注']]
    data=upload_simple(client,incoming,'资料提供公司')
    response=confirm_simple(client,data)
    assert response.status_code==200,response.text
    p=detail(client,old['id'])
    for field in ('manufacturer_name','parameters','selling_points'):
        assert p[field]==old[field]
    full=p['sources'][0]
    assert full['raw_values']['values']['产品参数']=='完整新参数\n第二段'
    assert full['raw_values']['values']['卖点']=='完整新卖点\n第二项' and full['notes']=='新价格条件备注'
    assert full['supplier_name']=='资料提供公司' and full['file_name']=='simple.xlsx'
    assert p['version']==old['version']+1
    with Session(engine) as db:
        assert db.get(LibraryImport,data['import_id']).status == 'committed'
    repeated=upload_simple(client,incoming,'资料提供公司')
    assert confirm_simple(client,repeated).status_code==200
    assert len(detail(client,old['id'])['sources'])==1


@pytest.mark.parametrize('existing',[False,True])
def test_multiple_source_companies_require_explicit_main_row_attribution(library,existing):
    client,_=library
    if existing:
        assert client.post(BASE+'/products',json={'model':'X','name':'产品','parameters':'旧参数'}).status_code==201
    data=upload_simple(client,[[None,'X','产品','主行原文']],'公司乙')
    assert confirm_simple(client,data).status_code==200
    data=upload_simple(client,[[None,'X','产品','另一份原文']],'公司甲')
    assert confirm_simple(client,data).status_code==200
    p=detail(client)
    assert p['manufacturer_name'] is None
    assert {source['supplier_name'] for source in p['sources']} == {'公司甲','公司乙'}
    assert next(source for source in p['sources'] if source['supplier_name']=='公司乙')['raw_values']['values']['产品参数']=='主行原文'


def test_main_row_provenance_cannot_be_silently_skipped(library):
    client,_=library
    data=upload_simple(client,[[None,'X','产品','必须保留的原文']],'公司')
    assert confirm_simple(client,data,[{'row_number':2,'action':'skip'}]).status_code==200
    assert client.get(BASE+'/products').json()['total']==0
    data=upload_simple(client,[[None,'X','产品','必须保留的原文']],'公司')
    assert confirm_simple(client,data).status_code==200
    assert detail(client)['sources'][0]['raw_values']['values']['产品参数']=='必须保留的原文'


def test_old_v2_ready_requires_repreview_but_committed_receipt_still_replays(library):
    from uuid import uuid4
    from app.product_library_v2_import import decision_digest
    from app.product_library_service import now
    client,engine=library
    ready_id,saved_id=str(uuid4()),str(uuid4())
    payload={'decisions':[{'row_key':{'sheet':'产品数据','temp_id':'P'},'action':'skip_product'}],'confirmed_attachments_not_imported':True}
    result={'import_id':saved_id,'template_version':2,'rows':[{'outcome':'skipped'}]}
    with Session(engine) as db:
        db.add(LibraryImport(import_id=ready_id,manufacturer_name='旧公司',created_at=now(),expires_at=now(),status='ready',preview={'template_version':2}))
        db.add(LibraryImport(import_id=saved_id,manufacturer_name='旧公司',created_at=now(),expires_at=now(),status='committed',result=result,decision_digest=decision_digest(payload)))
        db.commit()
    assert client.get(BASE+f'/imports/{ready_id}').json()['code']=='preview_rule_changed'
    assert client.post(BASE+f'/imports/{ready_id}/confirm',json=payload).status_code==409
    assert client.get(BASE+f'/imports/{saved_id}').json()==result
    assert client.post(BASE+f'/imports/{saved_id}/confirm',json=payload).json()==result


def test_main_row_source_failure_rolls_back_explicit_source_and_receipt(library):
    from sqlalchemy.exc import OperationalError
    client,engine=library
    old=client.post(BASE+'/products',json={'model':'X','name':'产品','parameters':'旧参数'}).json()
    data=upload_simple(client,[[None,'X','产品','主行事务哨兵']],'明确公司')
    def fail(connection,cursor,statement,parameters,context,executemany):
        if statement.startswith('INSERT INTO library_simple_sources'):
            raise OperationalError(statement,parameters,Exception('injected main-row source failure'))
    event.listen(engine,'before_cursor_execute',fail)
    try:
        assert confirm_simple(client,data).json()['code']=='import_save_failed'
    finally:
        event.remove(engine,'before_cursor_execute',fail)
    assert detail(client,old['id'])==old
    with Session(engine) as db:
        assert db.get(LibraryImport,data['import_id']).status=='ready'
    assert confirm_simple(client,data).status_code==200
    assert detail(client)['sources'][0]['raw_values']['values']['产品参数']=='主行事务哨兵'


def test_explicit_full_excerpt_reused_without_duplicate_provenance(library):
    client,_=library
    rows=[[None,'X','产品','新原文']]
    data=upload_simple(client,rows,'明确公司')
    assert confirm_simple(client,data).status_code==200
    repeated=upload_simple(client,rows,'明确公司')
    assert confirm_simple(client,repeated).status_code==200
    assert len(detail(client)['sources'])==1
    assert detail(client)['sources'][0]['raw_values']['values']['产品参数']=='新原文'
