import re

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import SystemSetting
from app.ownership import MAX_OWN_SHOP_NAME_LENGTH, OWN_SHOP_NAME_KEY, get_own_shop_name, normalize_shop_name, reconcile_ownership


router = APIRouter(prefix="/api/settings", tags=["settings"])


COMPETITOR_MONITORING_SETTINGS = {
    "item_interval_seconds": ("competitor_monitoring_item_interval_seconds", 5, 1, 60, False),
    "continuous_collection_count": ("competitor_monitoring_continuous_collection_count", 10, 1, 50, False),
    "batch_rest_seconds": ("competitor_monitoring_batch_rest_seconds", 120, 0, 1800, True),
    "verification_cooldown_seconds": ("competitor_monitoring_verification_cooldown_seconds", 600, 60, 3600, True),
    "auto_resume_max": ("competitor_monitoring_auto_resume_max", 2, 0, 5, False),
}


def competitor_monitoring_defaults() -> dict[str, int]:
    """Return the only business defaults for competitor-monitoring settings."""
    return {field: definition[1] for field, definition in COMPETITOR_MONITORING_SETTINGS.items()}


def _valid_monitoring_value(value: object, minimum: int, maximum: int, minute_multiple: bool) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and minimum <= value <= maximum
        and (not minute_multiple or value % 60 == 0)
    )


def get_competitor_monitoring_settings(db: Session) -> dict[str, int]:
    # A batch start must observe one database snapshot.  In particular, do not
    # turn this into one get() per key: PUT commits all five settings together.
    keys = [definition[0] for definition in COMPETITOR_MONITORING_SETTINGS.values()]
    stored = {
        setting.key: setting.value
        for setting in db.scalars(select(SystemSetting).where(SystemSetting.key.in_(keys)))
    }
    values: dict[str, int] = {}
    for field, (key, default, minimum, maximum, minute_multiple) in COMPETITOR_MONITORING_SETTINGS.items():
        raw = stored.get(key)
        if not isinstance(raw, str) or re.fullmatch(r"[0-9]+", raw) is None:
            values[field] = default
            continue
        try:
            parsed = int(raw)
        except (TypeError, ValueError):
            # Python deliberately rejects unbounded decimal strings.  Legacy
            # settings are untrusted input, so fall back without writing them.
            values[field] = default
            continue
        values[field] = parsed if _valid_monitoring_value(parsed, minimum, maximum, minute_multiple) else default
    return values


def validate_competitor_monitoring_settings(payload: object) -> dict[str, int]:
    if not isinstance(payload, dict) or set(payload) != set(COMPETITOR_MONITORING_SETTINGS):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "invalid_competitor_monitoring_settings", "message": "必须完整提交五项竞品监控设置"})
    values: dict[str, int] = {}
    for field, (_key, _default, minimum, maximum, minute_multiple) in COMPETITOR_MONITORING_SETTINGS.items():
        value = payload[field]
        if not _valid_monitoring_value(value, minimum, maximum, minute_multiple):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "invalid_competitor_monitoring_settings", "field": field, "message": f"{field} 参数无效"})
        values[field] = value
    return values


class OwnShopNameRequest(BaseModel):
    own_shop_name: str


def _payload(db: Session, *, reclassified_count: int | None = None, conflict_count: int | None = None) -> dict[str, object]:
    value = get_own_shop_name(db)
    result: dict[str, object] = {"configured": value is not None, "own_shop_name": value}
    if reclassified_count is not None:
        result["reclassified_count"] = reclassified_count
        result["conflict_count"] = conflict_count or 0
    return result


@router.get("/own-shop-name")
def get_own_shop_name_setting(db: Session = Depends(get_db)) -> dict[str, object]:
    return _payload(db)


@router.put("/own-shop-name")
def update_own_shop_name(payload: OwnShopNameRequest, db: Session = Depends(get_db)) -> dict[str, object]:
    value = normalize_shop_name(payload.own_shop_name)
    if not value or len(value) > MAX_OWN_SHOP_NAME_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_own_shop_name", "message": "请输入有效的我方店铺名称"},
        )
    setting = db.get(SystemSetting, OWN_SHOP_NAME_KEY)
    if setting is None:
        setting = SystemSetting(key=OWN_SHOP_NAME_KEY, value=value)
        db.add(setting)
    else:
        setting.value = value
    summary = reconcile_ownership(db, value)
    db.commit()
    return _payload(db, **summary)


@router.get("/competitor-monitoring")
def get_competitor_monitoring_setting(db: Session = Depends(get_db)) -> dict[str, int]:
    return get_competitor_monitoring_settings(db)


@router.put("/competitor-monitoring")
def update_competitor_monitoring_setting(
    payload: object = Body(...), db: Session = Depends(get_db)
) -> dict[str, int]:
    values = validate_competitor_monitoring_settings(payload)
    try:
        for field, (key, _default, _minimum, _maximum, _minute_multiple) in COMPETITOR_MONITORING_SETTINGS.items():
            setting = db.get(SystemSetting, key)
            if setting is None:
                db.add(SystemSetting(key=key, value=str(values[field])))
            else:
                setting.value = str(values[field])
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail={"code": "competitor_monitoring_settings_save_failed", "message": "竞品监控设置保存失败"}) from exc
    return values
