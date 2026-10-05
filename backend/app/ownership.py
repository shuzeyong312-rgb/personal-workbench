import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Competitor, CompetitorGroup, SystemSetting


OWN_SHOP_NAME_KEY = "own_shop_name"
DEFAULT_OWN_SHOP_NAME = "广州莓有科技有限公司"
MAX_OWN_SHOP_NAME_LENGTH = 255
_WHITESPACE = re.compile(r"\s+")


def normalize_shop_name(value: str) -> str:
    return _WHITESPACE.sub(" ", value.strip())


def get_own_shop_name(db: Session) -> str | None:
    setting = db.get(SystemSetting, OWN_SHOP_NAME_KEY)
    if setting is None or setting.value is None:
        return None
    value = normalize_shop_name(setting.value)
    return value or None


def identify_ownership(shop_name: str | None, own_shop_name: str | None) -> str | None:
    if not shop_name or not normalize_shop_name(shop_name) or not own_shop_name:
        return None
    return "self" if normalize_shop_name(shop_name) == normalize_shop_name(own_shop_name) else "competitor"


def _group_winner(members: list[Competitor]) -> Competitor | None:
    real_self = [member for member in members if member.ownership == "self" and member.shop_name is not None]
    fallback_self = [member for member in members if member.ownership == "self" and member.shop_name is None]
    candidates = real_self or fallback_self
    if not candidates:
        return None
    return min(candidates, key=lambda member: (member.created_at, member.id))


def reconcile_ownership(db: Session, own_shop_name: str) -> dict[str, int]:
    normalized_name = normalize_shop_name(own_shop_name)
    competitors = list(db.scalars(select(Competitor).order_by(Competitor.created_at.asc(), Competitor.id.asc())).all())
    changed = 0
    now = datetime.now(timezone.utc)
    for competitor in competitors:
        target = identify_ownership(competitor.shop_name, normalized_name)
        if target is not None and competitor.ownership != target:
            competitor.ownership = target
            competitor.updated_at = now
            changed += 1

    group_ids = {competitor.group_id for competitor in competitors if competitor.group_id is not None}
    conflicts = 0
    for group_id in sorted(group_ids):
        members = [competitor for competitor in competitors if competitor.group_id == group_id]
        winner = _group_winner(members)
        self_members = [member for member in members if member.ownership == "self"]
        if len(self_members) > 1:
            conflicts += len(self_members) - 1
        for member in members:
            if member.ownership != "self":
                if member.group_role != "competitor":
                    member.group_role = "competitor"
                    member.updated_at = now
                continue
            if winner is not None and member.id == winner.id:
                if member.group_role != "own":
                    member.group_role = "own"
                    member.updated_at = now
            else:
                if member.group_id is not None or member.group_role != "competitor":
                    member.group_id = None
                    member.group_role = "competitor"
                    member.updated_at = now

    for competitor in competitors:
        if competitor.group_id is None and competitor.group_role != "competitor":
            competitor.group_role = "competitor"
            competitor.updated_at = now
    return {"reclassified_count": changed, "conflict_count": conflicts}


def apply_collected_ownership(db: Session, competitor: Competitor, shop_name: str) -> str | None:
    own_shop_name = get_own_shop_name(db)
    target = identify_ownership(shop_name, own_shop_name)
    if target is None:
        return None
    original = (competitor.ownership, competitor.group_id, competitor.group_role)
    competitor.ownership = target
    now = datetime.now(timezone.utc)
    if target == "competitor":
        competitor.group_role = "competitor"
        if original != (competitor.ownership, competitor.group_id, competitor.group_role):
            competitor.updated_at = now
        return target
    if competitor.group_id is None:
        competitor.group_role = "competitor"
        if original != (competitor.ownership, competitor.group_id, competitor.group_role):
            competitor.updated_at = now
        return target

    competitor.group_role = "own"
    with db.no_autoflush:
        current_own = db.scalar(
            select(Competitor).where(
                Competitor.group_id == competitor.group_id,
                Competitor.group_role == "own",
                Competitor.id != competitor.id,
            )
        )
    if current_own is None:
        competitor.group_role = "own"
        return target
    if current_own.ownership == "self" and current_own.shop_name is None:
        current_own.group_id = None
        current_own.group_role = "competitor"
        current_own.updated_at = now
        db.flush([current_own])
        competitor.group_role = "own"
    else:
        competitor.group_id = None
        competitor.group_role = "competitor"
    if original != (competitor.ownership, competitor.group_id, competitor.group_role):
        competitor.updated_at = now
    return target
