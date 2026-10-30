"""Product library relational details and explicit legacy default prices."""
from alembic import op
import sqlalchemy as sa

revision = "20261029_21"
down_revision = "20261029_20"
branch_labels = None
depends_on = None

DDL = (
    """CREATE TABLE library_product_variants (
	id INTEGER NOT NULL,
	product_id INTEGER NOT NULL,
	variant_code VARCHAR(200),
	variant_name VARCHAR(200) NOT NULL,
	color VARCHAR(200),
	structured_attributes JSON,
	notes VARCHAR(10000),
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	version INTEGER NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (id, product_id),
	CHECK (version >= 1),
	FOREIGN KEY(product_id) REFERENCES library_products (id) ON DELETE CASCADE
)""",
    """CREATE UNIQUE INDEX uq_library_variant_code ON library_product_variants (product_id, variant_code) WHERE variant_code IS NOT NULL""",
    """CREATE UNIQUE INDEX uq_library_variant_name ON library_product_variants (product_id, variant_name, coalesce(color,'')) WHERE variant_code IS NULL""",
    """CREATE TABLE library_product_sources (
	id INTEGER NOT NULL,
	product_id INTEGER NOT NULL,
	source_company VARCHAR(200),
	claimed_manufacturer_name VARCHAR(200),
	source_file_name VARCHAR(500),
	source_page VARCHAR(500),
	source_date VARCHAR(10),
	source_type VARCHAR(16) NOT NULL,
	source_excerpt VARCHAR(30000),
	notes VARCHAR(10000),
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	version INTEGER NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (id, product_id),
	CHECK (version >= 1),
	CHECK (source_type IN ('quote','catalog','specification','other')),
	FOREIGN KEY(product_id) REFERENCES library_products (id) ON DELETE CASCADE
)""",
    """CREATE UNIQUE INDEX uq_library_source ON library_product_sources (product_id, coalesce(source_company,''), coalesce(source_file_name,''), coalesce(source_page,''), coalesce(source_date,''), coalesce(source_type,''), coalesce(source_excerpt,''))""",
    """CREATE TABLE library_product_prices (
	id INTEGER NOT NULL,
	product_id INTEGER NOT NULL,
	variant_id INTEGER,
	source_id INTEGER NOT NULL,
	price_type VARCHAR(32) NOT NULL,
	price_channel VARCHAR(200),
	amount_text VARCHAR(44),
	currency_code VARCHAR(3),
	price_unit VARCHAR(200),
	min_order_quantity VARCHAR(20),
	min_order_unit VARCHAR(200),
	tax_mode VARCHAR(16) NOT NULL,
	freight_mode VARCHAR(16) NOT NULL,
	freight_amount_cents INTEGER,
	customization_terms VARCHAR(10000),
	terms_text VARCHAR(10000),
	notes VARCHAR(10000),
	source_excerpt VARCHAR(10000),
	quote_date VARCHAR(10),
	is_default_wholesale BOOLEAN NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	version INTEGER NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(source_id, product_id) REFERENCES library_product_sources (id, product_id),
	FOREIGN KEY(variant_id, product_id) REFERENCES library_product_variants (id, product_id),
	CHECK (version >= 1),
	CHECK (price_type IN ('出厂价','批发价','一件代发价','定制价','平台控价','建议零售价','零售价','其他')),
	CHECK (tax_mode IN ('unknown','included','excluded')),
	CHECK (freight_mode IN ('unknown','included','excluded','extra','negotiable')),
	CHECK (amount_text IS NULL OR (length(amount_text)>0 AND amount_text NOT GLOB '*[^0-9.]*' AND CAST(amount_text AS NUMERIC)>=0)),
	CHECK (freight_amount_cents IS NULL OR freight_amount_cents >= 0),
	CHECK (is_default_wholesale IN (0,1) AND (is_default_wholesale=0 OR (price_type='批发价' AND currency_code='CNY' AND price_unit='件' AND amount_text IS NOT NULL AND CAST(amount_text AS NUMERIC)<=999999999.99))),
	FOREIGN KEY(product_id) REFERENCES library_products (id) ON DELETE CASCADE
)""",
    """CREATE UNIQUE INDEX uq_library_default_product ON library_product_prices (product_id) WHERE is_default_wholesale=1 AND variant_id IS NULL""",
    """CREATE UNIQUE INDEX uq_library_default_variant ON library_product_prices (product_id, variant_id) WHERE is_default_wholesale=1 AND variant_id IS NOT NULL""",
    """CREATE UNIQUE INDEX uq_library_price ON library_product_prices (product_id, source_id, coalesce(variant_id,''), coalesce(price_type,''), coalesce(price_channel,''), coalesce(currency_code,''), coalesce(price_unit,''), coalesce(quote_date,''), coalesce(min_order_quantity,''), coalesce(min_order_unit,''), coalesce(customization_terms,''))""",
)


def upgrade():
    bind = op.get_bind()
    if not bind.connection.driver_connection.in_transaction:
        bind.exec_driver_sql("BEGIN IMMEDIATE")
    op.add_column("library_products", sa.Column("category", sa.String(200)))
    op.add_column("library_products", sa.Column("structured_attributes", sa.JSON()))
    for statement in DDL:
        bind.exec_driver_sql(statement)
    products = bind.execute(sa.text("SELECT * FROM library_products ORDER BY id")).mappings().all()
    for product in products:
        bind.execute(sa.text("""INSERT INTO library_product_sources
            (product_id,source_company,source_type,notes,created_at,updated_at,version)
            VALUES (:id,:manufacturer_name,'other','legacy_backfill',:created_at,:updated_at,1)"""), dict(product))
        source_id = bind.exec_driver_sql("SELECT last_insert_rowid()").scalar_one()
        cents = product["wholesale_price_cents"]
        if cents is not None:
            if type(cents) is not int or not 0 <= cents <= 99999999999:
                raise RuntimeError("Invalid legacy amount; migration refused")
            amount = f"{cents // 100}.{cents % 100:02d}".rstrip('0').rstrip('.')
            bind.execute(sa.text("""INSERT INTO library_product_prices
                (product_id,source_id,price_type,amount_text,currency_code,price_unit,tax_mode,freight_mode,is_default_wholesale,created_at,updated_at,version)
                VALUES (:id,:source_id,'批发价',:amount,'CNY','件','unknown','unknown',1,:created_at,:updated_at,1)"""), {**dict(product), "source_id": source_id, "amount": amount})
    if bind.exec_driver_sql("PRAGMA foreign_key_check").all():
        raise RuntimeError("Foreign key check failed; migration refused")


def downgrade():
    raise RuntimeError("Unsafe downgrade: export incremental V2 data and restore a verified pre-upgrade backup")
