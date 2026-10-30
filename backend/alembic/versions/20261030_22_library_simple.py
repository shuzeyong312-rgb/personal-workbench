"""Archive PR #7 data and introduce the simple product library schema."""
from decimal import Decimal, InvalidOperation

from alembic import op
from sqlalchemy import text

from app.library_history_archive import archive_library_history

revision = "20261030_22"
down_revision = "20261029_21"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if not bind.connection.driver_connection.in_transaction:
        bind.exec_driver_sql("BEGIN IMMEDIATE")
    if bind.exec_driver_sql("PRAGMA integrity_check").scalar() != "ok" or bind.exec_driver_sql("PRAGMA foreign_key_check").all():
        raise RuntimeError("Database integrity check failed; migration refused")
    duplicates = bind.exec_driver_sql("SELECT model, name, group_concat(id) FROM library_products GROUP BY model, name HAVING count(*) > 1").all()
    if duplicates:
        raise RuntimeError(f"Duplicate product identities (model, name, product IDs): {duplicates!r}")

    products = bind.execute(text("SELECT * FROM library_products ORDER BY id")).mappings().all()
    for product in products:
        if product["wholesale_price_cents"] is None:
            continue
        legacy = bind.execute(text("""SELECT p.amount_text, p.currency_code, p.price_unit
            FROM library_product_prices p JOIN library_product_sources s ON s.id=p.source_id
            WHERE p.product_id=:id AND s.notes='legacy_backfill' AND p.variant_id IS NULL
              AND p.price_type='批发价'"""), {"id": product["id"]}).all()
        try:
            valid = len(legacy) == 1 and legacy[0][1:] == ("CNY", "件") and Decimal(legacy[0][0]) * 100 == product["wholesale_price_cents"]
        except (InvalidOperation, TypeError):
            valid = False
        if not valid:
            raise RuntimeError(f"Legacy price conflict for product id={product['id']}; migration refused")

    archive_library_history(bind)
    bind.exec_driver_sql("ALTER TABLE library_products RENAME TO library_products_legacy")
    bind.exec_driver_sql("DROP INDEX uq_library_products_model_name")
    bind.exec_driver_sql("DROP INDEX uq_library_products_null_model_name")
    bind.exec_driver_sql("""CREATE TABLE library_products (
        id INTEGER PRIMARY KEY AUTOINCREMENT, manufacturer_name VARCHAR(200), model VARCHAR(200),
        name VARCHAR(200) NOT NULL, parameters VARCHAR(10000), selling_points VARCHAR(10000),
        wholesale_price_cents INTEGER, price_note VARCHAR(2000), category VARCHAR(200),
        structured_attributes JSON, control_price VARCHAR(2000), archived_at DATETIME,
        created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, version INTEGER NOT NULL,
        CONSTRAINT ck_library_products_price CHECK (wholesale_price_cents IS NULL OR (wholesale_price_cents >= 0 AND wholesale_price_cents <= 99999999999)),
        CONSTRAINT ck_library_products_version CHECK (version >= 1))""")
    bind.exec_driver_sql("""INSERT INTO library_products
        (id,manufacturer_name,model,name,parameters,selling_points,wholesale_price_cents,price_note,category,structured_attributes,created_at,updated_at,version)
        SELECT id,manufacturer_name,model,name,parameters,selling_points,wholesale_price_cents,price_note,category,structured_attributes,created_at,updated_at,version
        FROM library_products_legacy""")
    bind.exec_driver_sql("CREATE UNIQUE INDEX uq_library_products_model_name ON library_products (model,name) WHERE model IS NOT NULL")
    bind.exec_driver_sql("CREATE UNIQUE INDEX uq_library_products_null_model_name ON library_products (name) WHERE model IS NULL")
    for table in ("library_products_legacy", "library_product_variants", "library_product_sources", "library_product_prices"):
        for action in ("INSERT", "UPDATE", "DELETE"):
            bind.exec_driver_sql(f'CREATE TRIGGER "{table}_no_{action.lower()}" BEFORE {action} ON "{table}" BEGIN SELECT RAISE(ABORT, \'library history is read-only\'); END')

    bind.exec_driver_sql("""CREATE TABLE library_simple_sources (
        id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES library_products(id),
        supplier_name VARCHAR(200) NOT NULL, source_type VARCHAR(16) NOT NULL,
        file_sha256 VARCHAR(64), file_name VARCHAR(500), sheet_name VARCHAR(200), row_number INTEGER,
        raw_values JSON, price_text VARCHAR(10000), notes VARCHAR(10000), manual_key VARCHAR(200) UNIQUE,
        created_at DATETIME NOT NULL, archived_at DATETIME, version INTEGER NOT NULL DEFAULT 1,
        UNIQUE(id,product_id), CHECK(version >= 1))""")
    bind.exec_driver_sql("CREATE UNIQUE INDEX uq_library_simple_file_row ON library_simple_sources (file_sha256,supplier_name,sheet_name,row_number) WHERE file_sha256 IS NOT NULL")
    bind.exec_driver_sql("""CREATE TABLE library_simple_quote_keys (
        id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES library_products(id),
        supplier_name VARCHAR(200) NOT NULL, variant VARCHAR(200), UNIQUE(id,product_id))""")
    bind.exec_driver_sql("CREATE UNIQUE INDEX uq_library_simple_quote_key ON library_simple_quote_keys (product_id,supplier_name,coalesce(variant,''))")
    bind.exec_driver_sql("""CREATE TABLE library_simple_quote_versions (
        id INTEGER PRIMARY KEY, quote_key_id INTEGER NOT NULL REFERENCES library_simple_quote_keys(id),
        version_number INTEGER NOT NULL, amount_cents INTEGER NOT NULL CHECK(amount_cents BETWEEN 0 AND 99999999999),
        currency VARCHAR(3) NOT NULL, unit VARCHAR(20) NOT NULL,
        eligibility VARCHAR(16) NOT NULL CHECK(eligibility IN ('pending','eligible','ineligible')),
        is_current INTEGER NOT NULL CHECK(is_current IN (0,1)), created_at DATETIME NOT NULL,
        UNIQUE(id,quote_key_id), UNIQUE(quote_key_id,version_number))""")
    bind.exec_driver_sql("CREATE UNIQUE INDEX uq_library_simple_current_quote ON library_simple_quote_versions (quote_key_id) WHERE is_current=1")
    bind.exec_driver_sql("""CREATE TABLE library_simple_quote_evidence (
        quote_version_id INTEGER NOT NULL, quote_key_id INTEGER NOT NULL, product_id INTEGER NOT NULL,
        source_id INTEGER NOT NULL,
        FOREIGN KEY(quote_version_id,quote_key_id) REFERENCES library_simple_quote_versions(id,quote_key_id),
        FOREIGN KEY(quote_key_id,product_id) REFERENCES library_simple_quote_keys(id,product_id),
        FOREIGN KEY(source_id,product_id) REFERENCES library_simple_sources(id,product_id),
        PRIMARY KEY(quote_version_id,source_id))""")
    bind.exec_driver_sql("""CREATE TABLE library_simple_eligibility_audit (
        id INTEGER PRIMARY KEY, quote_version_id INTEGER NOT NULL REFERENCES library_simple_quote_versions(id),
        before_status VARCHAR(16) NOT NULL, after_status VARCHAR(16) NOT NULL,
        reason TEXT NOT NULL, created_at DATETIME NOT NULL)""")
    bind.exec_driver_sql("""CREATE TABLE library_simple_product_events (
        id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES library_products(id),
        action VARCHAR(16) NOT NULL CHECK(action IN ('archive','restore')),
        product_version INTEGER NOT NULL, created_at DATETIME NOT NULL)""")
    bind.exec_driver_sql("""CREATE TABLE library_simple_source_events (
        id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES library_simple_sources(id),
        source_version INTEGER NOT NULL, created_at DATETIME NOT NULL)""")
    for table in ('library_simple_sources', 'library_simple_quote_keys', 'library_simple_quote_versions', 'library_simple_quote_evidence'):
        bind.exec_driver_sql(f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, 'library history cannot be deleted'); END")
    for table in ('library_simple_quote_keys', 'library_simple_quote_evidence'):
        bind.exec_driver_sql(f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, 'library history is immutable'); END")
    bind.exec_driver_sql("""CREATE TRIGGER library_simple_quote_values_immutable BEFORE UPDATE ON library_simple_quote_versions
        WHEN OLD.quote_key_id IS NOT NEW.quote_key_id OR OLD.version_number IS NOT NEW.version_number
          OR OLD.amount_cents IS NOT NEW.amount_cents OR OLD.currency IS NOT NEW.currency
          OR OLD.unit IS NOT NEW.unit OR OLD.created_at IS NOT NEW.created_at
        BEGIN SELECT RAISE(ABORT, 'quote version is immutable'); END""")
    for action in ("UPDATE", "DELETE"):
        bind.exec_driver_sql(f'CREATE TRIGGER library_simple_audit_no_{action.lower()} BEFORE {action} ON library_simple_eligibility_audit BEGIN SELECT RAISE(ABORT, \'audit is read-only\'); END')
        bind.exec_driver_sql(f'CREATE TRIGGER library_simple_event_no_{action.lower()} BEFORE {action} ON library_simple_product_events BEGIN SELECT RAISE(ABORT, \'audit is read-only\'); END')
        bind.exec_driver_sql(f'CREATE TRIGGER library_simple_source_event_no_{action.lower()} BEFORE {action} ON library_simple_source_events BEGIN SELECT RAISE(ABORT, \'audit is read-only\'); END')

    for product in products:
        params = dict(product)
        bind.execute(text("""INSERT INTO library_simple_sources
            (product_id,supplier_name,source_type,notes,created_at)
            VALUES (:id,:manufacturer_name,'legacy',:price_note,:created_at)"""), params)
        source_id = bind.exec_driver_sql("SELECT last_insert_rowid()").scalar_one()
        if product["wholesale_price_cents"] is not None:
            bind.execute(text("INSERT INTO library_simple_quote_keys (product_id,supplier_name) VALUES (:id,:manufacturer_name)"), params)
            key_id = bind.exec_driver_sql("SELECT last_insert_rowid()").scalar_one()
            bind.execute(text("""INSERT INTO library_simple_quote_versions
                (quote_key_id,version_number,amount_cents,currency,unit,eligibility,is_current,created_at)
                VALUES (:key,1,:amount,'CNY','件','pending',1,:created)"""),
                {"key": key_id, "amount": product["wholesale_price_cents"], "created": product["created_at"]})
            version_id = bind.exec_driver_sql("SELECT last_insert_rowid()").scalar_one()
            bind.execute(text("INSERT INTO library_simple_quote_evidence VALUES (:version,:key,:product,:source)"),
                         {"version": version_id, "key": key_id, "product": product["id"], "source": source_id})
    if bind.exec_driver_sql("PRAGMA foreign_key_check").all():
        raise RuntimeError("Foreign key check failed; migration refused")


def downgrade():
    raise RuntimeError("Unsafe downgrade: stop writes, export incremental data and restore a verified pre-upgrade backup")
