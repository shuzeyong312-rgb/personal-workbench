"""add ownership and own shop setting

Revision ID: 20261004_12
Revises: 20260923_11
"""

import re
import logging

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "20261004_12"
down_revision = "20260923_11"
branch_labels = None
depends_on = None

_WHITESPACE = re.compile(r"\s+")
DEFAULT_OWN_SHOP_NAME = "广州莓有科技有限公司"
logger = logging.getLogger(__name__)


def _normalize(value: str) -> str:
    return _WHITESPACE.sub(" ", value.strip())


def _set_sqlite_foreign_keys(enabled: bool) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.get_context().autocommit_block():
            bind.exec_driver_sql(f"PRAGMA foreign_keys={'ON' if enabled else 'OFF'}")


def _rebuild_legal_roles(bind, own_shop_name: str | None) -> None:
    rows = list(bind.execute(text(
        "SELECT id, group_id, group_role, ownership, shop_name, created_at "
        "FROM competitors ORDER BY created_at ASC, id ASC"
    )))
    for row in rows:
        ownership = (
            "self"
            if row.shop_name is None and row.group_role == "own"
            else "self"
            if row.shop_name is not None and own_shop_name is not None and _normalize(row.shop_name) == _normalize(own_shop_name)
            else "competitor"
        )
        bind.execute(text("UPDATE competitors SET ownership=:ownership, group_role='competitor' WHERE id=:id"),
                     {"ownership": ownership, "id": row.id})

    group_ids = [row[0] for row in bind.execute(text("SELECT DISTINCT group_id FROM competitors WHERE group_id IS NOT NULL"))]
    for group_id in group_ids:
        members = list(bind.execute(text(
            "SELECT id, group_id, group_role, ownership, shop_name, created_at "
            "FROM competitors WHERE group_id=:group_id ORDER BY created_at ASC, id ASC"
        ), {"group_id": group_id}))
        real_self = [row for row in members if row.ownership == "self" and row.shop_name is not None]
        fallback_self = [row for row in members if row.ownership == "self" and row.shop_name is None]
        candidates = real_self or fallback_self
        winner = candidates[0] if candidates else None
        losing_self_ids: list[int] = []
        for row in members:
            if row.ownership == "self" and winner is not None and row.id == winner.id:
                bind.execute(text("UPDATE competitors SET group_role='own' WHERE id=:id"), {"id": row.id})
            elif row.ownership == "self":
                losing_self_ids.append(row.id)
                bind.execute(text("UPDATE competitors SET group_id=NULL, group_role='competitor' WHERE id=:id"), {"id": row.id})
        if losing_self_ids:
            logger.warning(
                "ownership migration conflict: count=%d group_id=%s self_ids=%s winner=%s losing_self_ids=%s moved_to_unassigned",
                len(losing_self_ids),
                group_id,
                [row.id for row in members if row.ownership == "self"],
                winner.id if winner is not None else None,
                losing_self_ids,
            )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "system_settings" not in inspector.get_table_names():
        op.create_table(
            "system_settings",
            sa.Column("key", sa.String(length=64), nullable=False),
            sa.Column("value", sa.String(length=255), nullable=True),
            sa.PrimaryKeyConstraint("key"),
        )
    bind.execute(
        text("INSERT INTO system_settings (key, value) VALUES ('own_shop_name', :value) "
             "ON CONFLICT(key) DO NOTHING"),
        {"value": DEFAULT_OWN_SHOP_NAME},
    )

    _set_sqlite_foreign_keys(False)
    op.drop_index("uq_competitors_group_own", table_name="competitors")
    with op.batch_alter_table("competitors", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("ownership", sa.String(length=16), server_default="competitor", nullable=False))
    _set_sqlite_foreign_keys(True)

    setting = bind.execute(text("SELECT value FROM system_settings WHERE key='own_shop_name'")).scalar_one_or_none()
    _rebuild_legal_roles(bind, setting)

    _set_sqlite_foreign_keys(False)
    with op.batch_alter_table("competitors", recreate="always") as batch_op:
        batch_op.create_check_constraint("ck_competitors_ownership", "ownership IN ('self', 'competitor')")
        batch_op.create_check_constraint(
            "ck_competitors_ownership_role",
            "(ownership = 'competitor' AND group_role = 'competitor') OR "
            "(ownership = 'self' AND ((group_id IS NULL AND group_role = 'competitor') OR "
            "(group_id IS NOT NULL AND group_role = 'own')))" ,
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
    bind = op.get_bind()
    if bind.execute(text("SELECT 1 FROM competitors WHERE ownership='self' LIMIT 1")).first() is not None:
        raise RuntimeError("Cannot downgrade 20261004_12: competitors contains self ownership data.")

    _set_sqlite_foreign_keys(False)
    op.drop_index("uq_competitors_group_own", table_name="competitors")
    with op.batch_alter_table("competitors", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_competitors_ownership_role", type_="check")
        batch_op.drop_constraint("ck_competitors_ownership", type_="check")
        batch_op.drop_column("ownership")
    op.create_index(
        "uq_competitors_group_own",
        "competitors",
        ["group_id"],
        unique=True,
        sqlite_where=text("group_role = 'own'"),
    )
    op.drop_table("system_settings")
    _set_sqlite_foreign_keys(True)
