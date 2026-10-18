"""Independent manufacturer product library and durable import receipts."""

from alembic import op
import sqlalchemy as sa

revision = "20261018_16"
down_revision = "20261015_15"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "library_products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("manufacturer_name", sa.String(200), nullable=False),
        sa.Column("model", sa.String(200)),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("parameters", sa.String(10000)),
        sa.Column("selling_points", sa.String(10000)),
        sa.Column("wholesale_price_cents", sa.Integer()),
        sa.Column("price_note", sa.String(2000)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "wholesale_price_cents IS NULL OR (wholesale_price_cents >= 0 AND wholesale_price_cents <= 99999999999)",
            name="ck_library_products_price",
        ),
        sa.CheckConstraint("version >= 1", name="ck_library_products_version"),
        sqlite_autoincrement=True,
    )
    op.create_index(
        "uq_library_products_manufacturer_model",
        "library_products",
        ["manufacturer_name", "model"],
        unique=True,
        sqlite_where=sa.text("model IS NOT NULL"),
    )
    op.create_table(
        "library_imports",
        sa.Column("import_id", sa.String(36), primary_key=True),
        sa.Column("manufacturer_name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("preview", sa.JSON()),
        sa.Column("baseline_digest", sa.String(64)),
        sa.Column("decision_digest", sa.String(64)),
        sa.Column("result", sa.JSON()),
        sa.CheckConstraint(
            "status IN ('ready', 'committed')", name="ck_library_imports_status"
        ),
    )


def downgrade():
    # Downgrade permanently removes all library products and durable import receipts.
    op.drop_table("library_imports")
    op.drop_table("library_products")
