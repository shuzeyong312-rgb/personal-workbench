"""add group role to competitors

Revision ID: 20260923_11
Revises: 20260923_10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "20260923_11"
down_revision = "20260923_10"
branch_labels = None
depends_on = None


def _set_sqlite_foreign_keys(enabled: bool) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.get_context().autocommit_block():
            bind.exec_driver_sql(f"PRAGMA foreign_keys={'ON' if enabled else 'OFF'}")


def upgrade() -> None:
    _set_sqlite_foreign_keys(False)
    with op.batch_alter_table("competitors", recreate="always") as batch_op:
        batch_op.add_column(
            sa.Column("group_role", sa.String(length=16), server_default="competitor", nullable=False)
        )
        batch_op.create_check_constraint(
            "ck_competitors_group_role",
            "group_role IN ('competitor', 'own')",
        )
        batch_op.create_check_constraint(
            "ck_competitors_own_requires_group",
            "group_id IS NOT NULL OR group_role = 'competitor'",
        )
    op.create_index(
        "uq_competitors_group_own",
        "competitors",
        ["group_id"],
        unique=True,
        sqlite_where=text("group_role = 'own'"),
    )
    _set_sqlite_foreign_keys(True)


def downgrade() -> None:
    has_own_product = op.get_bind().execute(
        text("SELECT 1 FROM competitors WHERE group_role = 'own' LIMIT 1")
    ).first()
    if has_own_product is not None:
        raise RuntimeError(
            "Cannot downgrade 20260923_11: competitors contains own product role data."
        )

    _set_sqlite_foreign_keys(False)
    op.drop_index("uq_competitors_group_own", table_name="competitors")
    with op.batch_alter_table("competitors", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_competitors_group_role", type_="check")
        batch_op.drop_constraint("ck_competitors_own_requires_group", type_="check")
        batch_op.drop_column("group_role")
    _set_sqlite_foreign_keys(True)
