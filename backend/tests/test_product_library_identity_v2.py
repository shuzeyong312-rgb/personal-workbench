"""Identity V2 uses real APIs and SQLite, including actual Alembic transitions."""
import copy
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from test_product_library import library, product, preview, confirm
from test_collection_batches_migration import run_command
from app.models import LibraryImport, LibraryProduct
from app.product_library_service import digest, now

BASE = "/api/product-library"
OLD = "20261018_16"
NEW = "20261020_17"


def submit(client, data, choices):
    return client.post(f"{BASE}/imports/{data['import_id']}/confirm", json={"decisions": choices})


def update_choice(row, candidate):
    return {"row_number": row["row_number"], "action": "update", "target_id": candidate["id"], "target_version": candidate["version"]}


def test_manual_identity_matrix_edit_stable_id_and_exact_collision(library):
    client, _ = library
    a = client.post(BASE + '/products', json={'model': 'M', 'name': '红色 10W'}).json()
    assert client.post(BASE + "/products", json={"model": "M", "name": "红色 10W", "allow_suspected_duplicate": True}).json()["code"] == "product_exists"
    for model, name in [("M", "蓝色 10W"), ("N", "红色 10W"), (None, "红色 10W")]:
        payload = {"model": model, "name": name, "allow_suspected_duplicate": True}
        response = client.post(BASE + "/products", json=payload)
        assert response.status_code == 201
    assert client.post(BASE+'/products',json={'model':'M','name':'红色 10W'}).status_code==409
    b = client.post(BASE + '/products', json={'model': 'M', 'name': '绿色 10W'}).json()
    payload = {key: b[key] for key in ("model", "name", "parameters", "selling_points", "category", "control_price", "version")}
    payload["name"] = a["name"]
    response = client.put(f"{BASE}/products/{b['id']}", json={**payload, "allow_suspected_duplicate": True})
    assert response.status_code == 409 and response.json()["code"] == "product_exists"
    payload["name"] = "更名 20W"
    changed = client.put(f"{BASE}/products/{b['id']}", json={**payload, "allow_suspected_duplicate": True}).json()
    assert changed["id"] == b["id"] and changed["version"] == b["version"] + 1
    assert client.put(f"{BASE}/products/{b['id']}", json={**payload, "allow_suspected_duplicate": True}).status_code == 409
    assert client.get(BASE + "/products", params={"q": "更名", "page_size": 1}).json()["total"] == 1


@pytest.mark.parametrize("rows,invalid", [
    ([["M", "A"], ["M", "A"]], [True, True]),
    ([["M", "A"], ["M", "B"]], [False, False]),
    ([["M", "A"], ["N", "A"]], [False, False]),
    ([[None, "A"], [None, "A"]], [True, True]),
    ([[None, "A", "规格1"], [None, "A", "规格2"]], [True, True]),
])
def test_file_identity_matrix(library, rows, invalid):
    client, _ = library
    data = preview(client, rows).json()
    assert data["identity_rule_version"] == 4
    assert [bool(row['errors']) for row in data['rows']] == invalid
    choices = [{'row_number': row['row_number'], 'action': 'skip' if bad else 'apply'} for row, bad in zip(data['rows'], invalid)]
    result = client.post(f"{BASE}/imports/{data['import_id']}/confirm", json={'decisions': choices, 'confirmed_attachments_not_imported': True})
    assert result.status_code == 200
    assert client.get(BASE + "/products").json()["total"] == invalid.count(False)


def test_partial_matches_are_new_and_import_idempotency_remains(library):
    client, _ = library
    a = client.post(BASE + '/products', json={'model': 'M', 'name': 'A', 'parameters': '原A'}).json()
    b = client.post(BASE + '/products', json={'model': 'M', 'name': 'B', 'parameters': '原B'}).json()
    data = preview(client, [["M", "C", None, "新卖点"]]).json()
    row = data["rows"][0]
    assert row['product_id'] is None and not row['errors'] and not row['potential_duplicates']
    choice = {"row_number": 2, "action": "apply"}
    payload = {'decisions': [choice], 'confirmed_attachments_not_imported': True}
    endpoint = f"{BASE}/imports/{data['import_id']}/confirm"
    result = client.post(endpoint, json=payload)
    assert result.status_code == 200 and result.json()['rows'][0]['action'] == 'imported'
    assert client.post(endpoint, json=payload).json() == result.json()
    assert client.post(endpoint, json={**payload, 'decisions': [{'row_number': 2, 'action': 'skip'}]}).status_code == 409
    assert client.get(f"{BASE}/products/{a['id']}").json() == a
    assert client.get(f"{BASE}/products/{b['id']}").json() == b


def test_exact_match_noop_and_field_update_only_exact_target(library):
    client, _ = library
    a = client.post(BASE + '/products', json={'model': 'M', 'name': 'A', 'parameters': 'old'}).json()
    assert client.post(BASE + '/products', json={'model': 'M', 'name': 'B'}).status_code == 201
    noop = preview(client, [["M", "A"]]).json()
    assert noop['rows'][0]['product_id'] == a['id'] and noop['rows'][0]['differences'] == {}
    data = preview(client, [["M", "A", "new"]]).json()
    row = data["rows"][0]
    assert row['product_id'] == a['id'] and row['differences']['parameters'] == {'current': 'old', 'incoming': 'new'}
    result = client.post(f"{BASE}/imports/{data['import_id']}/confirm", json={'confirmed_attachments_not_imported': True, 'decisions': [{'row_number': 2, 'action': 'apply', 'update_fields': ['parameters']}]})
    assert result.status_code == 200
    assert client.get(f"{BASE}/products/{a['id']}").json()['parameters'] == 'new'


def test_plan_rejects_two_rows_overwriting_same_target_and_unique_conflicts(library):
    client, engine = library
    a = client.post(BASE + '/products', json={'model': 'M', 'name': 'A', 'parameters': 'old'}).json()
    data = preview(client, [["M", "A", "first"], ["M", "A", "second"]]).json()
    assert all(row['errors'] for row in data['rows'])
    choices = [{'row_number': row['row_number'], 'action': 'apply'} for row in data['rows']]
    response = client.post(f"{BASE}/imports/{data['import_id']}/confirm", json={'confirmed_attachments_not_imported': True, 'decisions': choices})
    assert response.status_code == 422
    assert client.get(f"{BASE}/products/{a['id']}").json() == a
    with Session(engine) as db:
        db.add(LibraryProduct(manufacturer_name="厂家", model="M", name="A", version=1, created_at=now(), updated_at=now()))
        with pytest.raises(IntegrityError):
            db.commit()
    assert client.get(BASE + "/products").json()["total"] == 1


def test_old_ready_rejected_and_old_committed_replays_without_schema_gate(library):
    from uuid import uuid4
    from app.product_library_v2_import import decision_digest
    client, engine = library
    ready = preview(client, [["M", "A"]]).json()
    committed_id = str(uuid4())
    old_payload = {'decisions': [{'action': 'skip_product', 'row_key': {'sheet': '产品数据', 'temp_id': 'P'}}], 'confirmed_attachments_not_imported': True}
    result = {'import_id': committed_id, 'template_version': 2, 'rows': [{'outcome': 'skipped'}]}
    with Session(engine) as db:
        item = db.get(LibraryImport, ready["import_id"])
        old = copy.deepcopy(item.preview); old.pop("identity_rule_version"); item.preview = old
        db.add(LibraryImport(import_id=committed_id, manufacturer_name='旧资料公司', created_at=now(), expires_at=now() - timedelta(days=1), status='committed', result=result, decision_digest=decision_digest(old_payload)))
        db.commit()
    assert client.get(f"{BASE}/imports/{ready['import_id']}").json()["code"] == "preview_rule_changed"
    simple_payload = {'confirmed_attachments_not_imported': True, 'decisions': [{'row_number': 2, 'action': 'apply'}]}
    assert client.post(f"{BASE}/imports/{ready['import_id']}/confirm", json=simple_payload).status_code == 409
    # Recreate old schema on this isolated database only.
    with engine.begin() as connection:
        connection.execute(text("CREATE UNIQUE INDEX uq_library_products_manufacturer_model ON library_products(manufacturer_name,model) WHERE model IS NOT NULL"))
        connection.execute(text("DROP INDEX uq_library_products_model_name"))
    assert client.get(f"{BASE}/imports/{committed_id}").json() == result
    assert client.post(f"{BASE}/imports/{committed_id}/confirm", json=old_payload).json() == result
    assert client.post(BASE + "/products", json={"model": "Z", "name": "Z"}).json()["code"] == "identity_schema_required"
    assert preview(client, [["Q", "Q"]]).json()["code"] == "identity_schema_required"
    with Session(engine) as db:
        assert db.get(LibraryImport, ready["import_id"]).status == "ready"


def test_new_preview_expiry_and_manufacturer_changes(library):
    client, engine = library
    data = preview(client, [["M", "A"]]).json()
    with Session(engine) as db:
        db.get(LibraryImport, data["import_id"]).expires_at = now() - timedelta(seconds=1); db.commit()
    choices = {'confirmed_attachments_not_imported': True, 'decisions': [{'row_number': 2, 'action': 'apply'}]}
    assert client.post(f"{BASE}/imports/{data['import_id']}/confirm", json=choices).json()["code"] == "import_stale"
    data = preview(client, [["M", "A"]]).json()
    assert client.post(BASE + '/products', json={'model': 'M', 'name': 'A'}).status_code == 201
    assert client.post(f"{BASE}/imports/{data['import_id']}/confirm", json=choices).json()["code"] == "import_stale"


def seed_old(url):
    run_command(url, OLD)
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO library_products(id,manufacturer_name,model,name,parameters,wholesale_price_cents,created_at,updated_at,version) VALUES (7,'厂家','M','原名','红色 10W',1234,'2026-10-18','2026-10-18',3)"))
    engine.dispose()


def snapshot(url):
    engine = create_engine(url)
    with engine.connect() as connection:
        state = {"products": connection.execute(text("SELECT * FROM library_products ORDER BY id")).all(), "revision": connection.execute(text("SELECT version_num FROM alembic_version")).scalar(), "indexes": inspect(connection).get_indexes("library_products")}
        assert connection.execute(text("PRAGMA integrity_check")).scalar() == "ok"
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    engine.dispose()
    return state


def test_real_migration_preserves_data_and_blocks_unsafe_downgrade(tmp_path):
    url = f"sqlite:///{(tmp_path/'migration.db').as_posix()}"
    seed_old(url)
    before = snapshot(url)
    run_command(url, NEW)
    after = snapshot(url)
    assert before["products"] == after["products"] and after["revision"] == NEW
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO library_products(manufacturer_name,model,name,created_at,updated_at,version) VALUES ('厂家','M','独立名','2026-10-20','2026-10-20',1)"))
        with pytest.raises(IntegrityError):
            connection.execute(text("INSERT INTO library_products(manufacturer_name,model,name,created_at,updated_at,version) VALUES ('厂家','M','独立名','2026-10-20','2026-10-20',1)"))
    engine.dispose()
    with pytest.raises(RuntimeError, match="Unsafe downgrade"):
        run_command(url, OLD, downgrade=True)
    current = snapshot(url)
    assert current["revision"] == NEW and len(current["products"]) == 2
    # Independently rehearse compatible downgrade without deleting any record.
    url2 = f"sqlite:///{(tmp_path/'compatible.db').as_posix()}"
    seed_old(url2); run_command(url2, NEW); run_command(url2, OLD, downgrade=True)
    assert snapshot(url2)["products"] == before["products"]


@pytest.mark.parametrize("stage", ["drop", "stamp"])
def test_migration_failure_rolls_back_indexes_data_and_revision(tmp_path, stage):
    url = f"sqlite:///{(tmp_path/f'failed-{stage}.db').as_posix()}"
    seed_old(url)
    before = snapshot(url)
    def fail(connection, cursor, statement, parameters, context, executemany):
        if (stage == "drop" and "DROP INDEX uq_library_products_manufacturer_model" in statement or stage == "stamp" and statement.startswith("UPDATE alembic_version") and NEW in (statement + str(parameters))):
            raise RuntimeError("injected migration failure")
    event.listen(Engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            run_command(url, NEW)
    finally:
        event.remove(Engine, "before_cursor_execute", fail)
    after = snapshot(url)
    assert before["products"] == after["products"] and after["revision"] == OLD
    assert [index["name"] for index in after["indexes"]] == [index["name"] for index in before["indexes"]]


def test_noncanonical_legacy_data_is_blocked_without_rewriting(tmp_path):
    url = f"sqlite:///{(tmp_path/'noncanonical.db').as_posix()}"
    seed_old(url)
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("UPDATE library_products SET name=' 原名 '"))
    engine.dispose()
    before = snapshot(url)
    with pytest.raises(RuntimeError, match="Noncanonical"):
        run_command(url, NEW)
    assert snapshot(url)["products"] == before["products"]
    assert snapshot(url)["revision"] == OLD


def test_legacy_null_model_exact_duplicates_block_migration_without_changes(tmp_path):
    url = f"sqlite:///{(tmp_path/'null-model-duplicates.db').as_posix()}"
    seed_old(url)
    engine = create_engine(url)
    with engine.begin() as connection:
        for _ in range(2):
            connection.execute(text("INSERT INTO library_products(manufacturer_name,model,name,created_at,updated_at,version) VALUES ('厂家',NULL,'无型号同名','2026-10-18','2026-10-18',1)"))
    engine.dispose()
    before = snapshot(url)
    with pytest.raises(RuntimeError, match="Exact duplicate product identity"):
        run_command(url, NEW)
    after = snapshot(url)
    assert after["products"] == before["products"] and after["revision"] == OLD
    for state in (before, after):
        for index in state["indexes"]:
            index["dialect_options"]["sqlite_where"] = str(index["dialect_options"]["sqlite_where"])
    assert after["indexes"] == before["indexes"]

@pytest.mark.parametrize("replacement", [
    "CREATE INDEX uq_library_products_model_name ON library_products(manufacturer_name,model,name) WHERE model IS NOT NULL",
    "CREATE UNIQUE INDEX uq_library_products_model_name ON library_products(manufacturer_name,model) WHERE model IS NOT NULL",
    "CREATE UNIQUE INDEX uq_library_products_model_name ON library_products(manufacturer_name,model,name)",
    "CREATE UNIQUE INDEX uq_library_products_model_name ON library_products(manufacturer_name,model,name) WHERE name IS NOT NULL",
])
def test_schema_gate_checks_actual_constraint_not_only_name(library, replacement):
    client, engine = library
    p = client.post(BASE + '/products', json={'model': 'M1', 'name': '风扇'}).json()
    data = preview(client, [["NEW", "新增"]]).json()
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX uq_library_products_model_name"))
        connection.execute(text(replacement))
    result = client.post(f"{BASE}/imports/{data['import_id']}/confirm", json={'confirmed_attachments_not_imported': True, 'decisions': [{'row_number': 2, 'action': 'apply'}]})
    assert result.json()["code"] == "identity_schema_required"
    payload = {key: p[key] for key in ("model", "name", "category", "parameters", "control_price", "selling_points", "version")}
    assert client.put(f"{BASE}/products/{p['id']}", json=payload).json()["code"] == "identity_schema_required"
    assert client.get(f"{BASE}/products/{p['id']}").json() == p


def test_concurrent_exact_creates_and_independent_same_model(library):
    from concurrent.futures import ThreadPoolExecutor
    client, _ = library
    payload = {"model": "M", "name": "同名", "allow_suspected_duplicate": True}
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post(BASE + "/products", json=payload), range(2)))
    assert sorted(response.status_code for response in responses) == [201, 409]
    assert client.get(BASE + "/products").json()["total"] == 1
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda name: client.post(BASE + "/products", json={**payload, "name": name}), ["独立A", "独立B"]))
    assert [response.status_code for response in responses] == [201, 201]
    quote = client.post(BASE + "/customer-quotations/preview", json={"scope": "all", "include_unquoted": True}).json()
    assert len({item["id"] for item in quote["items"]}) == 3


def test_identity_normalization_preserves_specs_case_and_width(library):
    client, _ = library
    a = client.post(BASE + '/products', json={'model': ' M ', 'name': ' 红色 10W\r\n20cm '}).json()
    assert (a["manufacturer_name"], a["model"], a["name"]) == (None, "M", "红色 10W\n20cm")
    duplicate = client.post(BASE + "/products", json={"model": "M", "name": "红色 10W\n20cm"})
    assert duplicate.json()["code"] == "product_exists"
    for model, name in [("m", a["name"]), ("Ｍ", a["name"]), ("M", "蓝色 10W\n20cm"), ("M", "红色 20W\n20cm")]:
        assert client.post(BASE + "/products", json={"model": model, "name": name, "allow_suspected_duplicate": True}).status_code == 201
