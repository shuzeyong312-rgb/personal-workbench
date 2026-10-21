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
    a = product(client, model="M", name="红色 10W", wholesale_price="12.00")
    assert client.post(BASE + "/products", json={"manufacturer_name": "厂家", "model": "M", "name": "红色 10W", "allow_suspected_duplicate": True}).json()["code"] == "product_exists"
    for model, name in [("M", "蓝色 10W"), ("N", "红色 10W"), (None, "红色 10W")]:
        payload = {"manufacturer_name": "厂家", "model": model, "name": name}
        response = client.post(BASE + "/products", json=payload)
        assert response.status_code == 201
    product(client, manufacturer_name="其他厂家", model="M", name="红色 10W")
    b = product(client, model="M", name="绿色 10W", allow_suspected_duplicate=True)
    payload = {key: b[key] for key in ("manufacturer_name", "model", "name", "parameters", "selling_points", "wholesale_price", "price_note", "version")}
    payload["name"] = a["name"]
    response = client.put(f"{BASE}/products/{b['id']}", json={**payload, "allow_suspected_duplicate": True})
    assert response.status_code == 409 and response.json()["code"] == "product_exists"
    payload["name"] = "更名 20W"
    changed = client.put(f"{BASE}/products/{b['id']}", json={**payload, "allow_suspected_duplicate": True}).json()
    assert changed["id"] == b["id"] and changed["version"] == b["version"] + 1
    assert client.put(f"{BASE}/products/{b['id']}", json={**payload, "allow_suspected_duplicate": True}).status_code == 409
    assert client.get(BASE + "/products", params={"q": "更名", "page_size": 1}).json()["total"] == 1


@pytest.mark.parametrize("rows,categories", [
    ([["M", "A"], ["M", "A"]], ["new", "duplicate"]),
    ([["M", "A"], ["M", "B"]], ["new", "new"]),
    ([["M", "A"], ["N", "A"]], ["new", "new"]),
    ([[None, "A"], [None, "A"]], ["new", "duplicate"]),
    ([[None, "A", "规格1"], [None, "A", "规格2"]], ["new", "duplicate"]),
])
def test_file_identity_matrix(library, rows, categories):
    client, _ = library
    data = preview(client, rows).json()
    assert data["identity_rule_version"] == 3
    assert [row["category"] for row in data["rows"]] == categories
    result = confirm(client, data)
    assert result.status_code == 200 and result.json()["inserted"] == categories.count("new")
    assert client.get(BASE + "/products").json()["total"] == categories.count("new")


def test_partial_matches_are_new_and_import_idempotency_remains(library):
    client, _ = library
    a = product(client, model="M", name="A", parameters="原A")
    b = product(client, model="M", name="B", parameters="原B", allow_suspected_duplicate=True)
    data = preview(client, [["M", "C", None, "新卖点"]]).json()
    row = data["rows"][0]
    assert row["category"] == "new" and row["allowed_actions"] == ["insert", "skip"]
    assert row["candidate"] == [] and row["file_candidates"] == []
    choice = {"row_number": 2, "action": "insert"}
    result = submit(client, data, [choice])
    assert result.status_code == 200 and result.json()["inserted"] == 1
    assert submit(client, data, [choice]).json() == result.json()
    assert submit(client, data, [{"row_number": 2, "action": "skip"}]).json()["code"] == "idempotency_conflict"
    assert client.get(f"{BASE}/products/{a['id']}").json() == a
    assert client.get(f"{BASE}/products/{b['id']}").json() == b


def test_exact_match_noop_and_field_update_only_exact_target(library):
    client, _ = library
    a = product(client, model="M", name="A", parameters="old")
    product(client, model="M", name="B")
    noop = preview(client, [["M", "A"]]).json()
    assert noop["rows"][0]["allowed_actions"] == ["skip"]
    data = preview(client, [["M", "A", "new"]]).json()
    row = data["rows"][0]
    assert row["category"] == "duplicate" and "insert" not in row["allowed_actions"]
    assert [c["id"] for c in row["candidate"] if c["can_update"]] == [a["id"]]
    assert confirm(client, data, {2: "update"}).json()["updated"] == 1


def test_plan_rejects_two_rows_overwriting_same_target_and_unique_conflicts(library):
    client, engine = library
    a = product(client, model="M", name="A", parameters="old")
    data = preview(client, [["M", "A", "first"], ["M", "A", "second"]]).json()
    choices = [update_choice(row, row["candidate"][0]) for row in data["rows"]]
    assert submit(client, data, choices).json()["code"] == "duplicate_update_target"
    assert client.get(f"{BASE}/products/{a['id']}").json() == a
    with Session(engine) as db:
        db.add(LibraryProduct(manufacturer_name="厂家", model="M", name="A", version=1, created_at=now(), updated_at=now()))
        with pytest.raises(IntegrityError):
            db.commit()
    assert client.get(BASE + "/products").json()["total"] == 1


def test_old_ready_rejected_and_old_committed_replays_without_schema_gate(library):
    client, engine = library
    ready = preview(client, [["M", "A"]]).json()
    committed = preview(client, [["N", "B"]]).json()
    result = confirm(client, committed).json()
    with Session(engine) as db:
        item = db.get(LibraryImport, ready["import_id"])
        old = copy.deepcopy(item.preview); old.pop("identity_rule_version"); item.preview = old
        item = db.get(LibraryImport, committed["import_id"])
        old = copy.deepcopy(item.result); old.pop("identity_rule_version"); item.result = old
        item.decision_digest = digest([(2, "insert")])
        item.expires_at = now() - timedelta(days=1)
        db.commit()
    for method in [lambda: client.get(f"{BASE}/imports/{ready['import_id']}"), lambda: confirm(client, ready)]:
        assert method().json()["code"] == "preview_rule_changed"
    # Recreate old schema on this isolated database only.
    with engine.begin() as connection:
        connection.execute(text("CREATE UNIQUE INDEX uq_library_products_manufacturer_model ON library_products(manufacturer_name,model) WHERE model IS NOT NULL"))
        connection.execute(text("DROP INDEX uq_library_products_manufacturer_model_name"))
    assert client.get(f"{BASE}/imports/{committed['import_id']}").json()["inserted"] == result["inserted"]
    assert confirm(client, committed).status_code == 200
    assert client.post(BASE + "/products", json={"manufacturer_name": "厂家", "model": "Z", "name": "Z"}).json()["code"] == "identity_schema_required"
    assert preview(client, [["Q", "Q"]]).json()["code"] == "identity_schema_required"
    with Session(engine) as db:
        assert db.get(LibraryImport, ready["import_id"]).status == "ready"


def test_new_preview_expiry_and_manufacturer_changes(library):
    client, engine = library
    data = preview(client, [["M", "A"]]).json()
    with Session(engine) as db:
        db.get(LibraryImport, data["import_id"]).expires_at = now() - timedelta(seconds=1); db.commit()
    assert confirm(client, data).json()["code"] == "preview_expired"
    data = preview(client, [["M", "A"]]).json()
    product(client, model="N", name="B")
    assert confirm(client, data).json()["code"] == "preview_stale"


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

@pytest.mark.parametrize("replacement", [
    "CREATE INDEX uq_library_products_manufacturer_model_name ON library_products(manufacturer_name,model,name) WHERE model IS NOT NULL",
    "CREATE UNIQUE INDEX uq_library_products_manufacturer_model_name ON library_products(manufacturer_name,model) WHERE model IS NOT NULL",
    "CREATE UNIQUE INDEX uq_library_products_manufacturer_model_name ON library_products(manufacturer_name,model,name)",
    "CREATE UNIQUE INDEX uq_library_products_manufacturer_model_name ON library_products(manufacturer_name,model,name) WHERE name IS NOT NULL",
])
def test_schema_gate_checks_actual_constraint_not_only_name(library, replacement):
    client, engine = library
    p = product(client)
    data = preview(client, [["NEW", "新增"]]).json()
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX uq_library_products_manufacturer_model_name"))
        connection.execute(text(replacement))
    assert confirm(client, data).json()["code"] == "identity_schema_required"
    payload = {key: p[key] for key in ("manufacturer_name", "model", "name", "parameters", "selling_points", "wholesale_price", "price_note", "version")}
    assert client.put(f"{BASE}/products/{p['id']}", json=payload).json()["code"] == "identity_schema_required"
    assert client.get(f"{BASE}/products/{p['id']}").json() == p


def test_concurrent_exact_creates_and_independent_same_model(library):
    from concurrent.futures import ThreadPoolExecutor
    client, _ = library
    payload = {"manufacturer_name": "厂家", "model": "M", "name": "同名", "allow_suspected_duplicate": True}
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
    a = product(client, manufacturer_name="  厂家   A ", model=" M ", name=" 红色 10W\r\n20cm ")
    assert (a["manufacturer_name"], a["model"], a["name"]) == ("厂家 A", "M", "红色 10W\n20cm")
    duplicate = client.post(BASE + "/products", json={"manufacturer_name": "厂家 A", "model": "M", "name": "红色 10W\n20cm"})
    assert duplicate.json()["code"] == "product_exists"
    for model, name in [("m", a["name"]), ("Ｍ", a["name"]), ("M", "蓝色 10W\n20cm"), ("M", "红色 20W\n20cm")]:
        assert client.post(BASE + "/products", json={"manufacturer_name": "厂家 A", "model": model, "name": name, "allow_suspected_duplicate": True}).status_code == 201
