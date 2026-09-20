"""create competitor groups and link competitors

Revision ID: 20260920_04
Revises: 20260919_03
"""

from alembic import op
import sqlalchemy as sa


revision = "20260920_04"
down_revision = "20260919_03"
branch_labels = None
depends_on = None


def _ensure_existing_group_ids_are_null() -> None:
    count = op.get_bind().execute(
        sa.text("SELECT COUNT(*) FROM competitors WHERE group_id IS NOT NULL")
    ).scalar_one()
    if count:
        raise RuntimeError(f"Cannot add competitor group foreign key: {count} non-null group_id values exist")


def _set_sqlite_foreign_keys(enabled: bool) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.get_context().autocommit_block():
            bind.exec_driver_sql(f"PRAGMA foreign_keys={'ON' if enabled else 'OFF'}")


def upgrade() -> None:
    _ensure_existing_group_ids_are_null()
    _set_sqlite_foreign_keys(False)
    op.create_table(
        "competitor_groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    with op.batch_alter_table("competitors", recreate="always") as batch_op:
        batch_op.create_foreign_key(
            "fk_competitors_group_id_competitor_groups",
            "competitor_groups",
            ["group_id"],
            ["id"],
        )
    _set_sqlite_foreign_keys(True)


def downgrade() -> None:
    _set_sqlite_foreign_keys(False)
    with op.batch_alter_table("competitors", recreate="always") as batch_op:
        batch_op.drop_constraint("fk_competitors_group_id_competitor_groups", type_="foreignkey")
    op.drop_table("competitor_groups")
    _set_sqlite_foreign_keys(True)
