import json
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
    "operating_metrics_retry_max": ("competitor_monitoring_operating_metrics_retry_max", 0, 0, 2, False),
}
AUTO_COLLECTION_SETTINGS = {
    "auto_collection_enabled": ("competitor_monitoring_auto_collection_enabled", True),
    "auto_collection_strategy": ("competitor_monitoring_auto_collection_strategy", "rolling_24h"),
    "auto_collection_time": ("competitor_monitoring_auto_collection_time", "09:30"),
    "auto_collection_times": ("competitor_monitoring_auto_collection_times", ["09:30"]),
    "auto_collection_interval_hours": ("competitor_monitoring_auto_collection_interval_hours", 4),
    "auto_collection_daily_limit": ("competitor_monitoring_auto_collection_daily_limit", 3),
    "auto_collection_missed_policy": ("competitor_monitoring_auto_collection_missed_policy", "catch_up"),
}

_TIME_PATTERN = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]")


def competitor_monitoring_defaults() -> dict[str, object]:
    """Return the only business defaults for competitor-monitoring settings."""
    return {
        **{field: definition[1] for field, definition in COMPETITOR_MONITORING_SETTINGS.items()},
        **{field: definition[1] for field, definition in AUTO_COLLECTION_SETTINGS.items()},
    }


def _valid_monitoring_value(value: object, minimum: int, maximum: int, minute_multiple: bool) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and minimum <= value <= maximum
        and (not minute_multiple or value % 60 == 0)
    )


def get_competitor_monitoring_settings(db: Session) -> dict[str, object]:
    # A batch start must observe one database snapshot; PUT commits these keys together.
    keys = [definition[0] for definition in COMPETITOR_MONITORING_SETTINGS.values()] + [definition[0] for definition in AUTO_COLLECTION_SETTINGS.values()]
    stored = {
        setting.key: setting.value
        for setting in db.scalars(select(SystemSetting).where(SystemSetting.key.in_(keys)))
    }
    values: dict[str, object] = {}
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
    for field in ("auto_collection_enabled", "auto_collection_strategy", "auto_collection_time", "auto_collection_missed_policy"):
        key, default = AUTO_COLLECTION_SETTINGS[field]
        raw = stored.get(key)
        if field == "auto_collection_enabled":
            values[field] = raw == "true" if raw in {"true", "false"} else default
        elif field == "auto_collection_strategy":
            values[field] = raw if raw in {"rolling_24h", "fixed_daily", "fixed_interval"} else default
        elif field == "auto_collection_time":
            values[field] = raw if isinstance(raw, str) and _TIME_PATTERN.fullmatch(raw) else default
        else:
            values[field] = raw if raw in {"catch_up", "skip"} else default
    times_key, default_times = AUTO_COLLECTION_SETTINGS["auto_collection_times"]
    try:
        raw_times = json.loads(stored[times_key])
    except (KeyError, TypeError, json.JSONDecodeError):
        raw_times = None
    if _valid_times(raw_times):
        values["auto_collection_times"] = sorted(raw_times)
    elif _TIME_PATTERN.fullmatch(str(values["auto_collection_time"])):
        # V1 stored one time under this key; use it without writing a migration.
        values["auto_collection_times"] = [values["auto_collection_time"]]
    else:
        values["auto_collection_times"] = default_times
    for field, minimum, maximum in (("auto_collection_interval_hours", 1, 24), ("auto_collection_daily_limit", 1, 12)):
        key, default = AUTO_COLLECTION_SETTINGS[field]
        raw = stored.get(key)
        try:
            parsed = int(raw) if isinstance(raw, str) and re.fullmatch(r"[0-9]+", raw) else default
        except ValueError:
            parsed = default
        values[field] = parsed if minimum <= parsed <= maximum else default
    if values["auto_collection_strategy"] == "fixed_interval" and not _valid_interval(values["auto_collection_time"], values["auto_collection_interval_hours"], values["auto_collection_daily_limit"]):
        values["auto_collection_time"] = "09:30"
        values["auto_collection_interval_hours"] = 4
        values["auto_collection_daily_limit"] = 3
    if values["auto_collection_strategy"] == "fixed_daily":
        values["auto_collection_time"] = values["auto_collection_times"][0]
    return values


def _valid_times(value: object) -> bool:
    return (
        isinstance(value, list)
        and 1 <= len(value) <= 8
        and all(isinstance(item, str) and _TIME_PATTERN.fullmatch(item) for item in value)
        and len(set(value)) == len(value)
    )


def _valid_interval(start: object, hours: object, count: object) -> bool:
    if not isinstance(start, str) or _TIME_PATTERN.fullmatch(start) is None:
        return False
    if type(hours) is not int or not 1 <= hours <= 24 or type(count) is not int or not 1 <= count <= 12:
        return False
    start_minutes = int(start[:2]) * 60 + int(start[3:])
    return start_minutes + (count - 1) * hours * 60 < 24 * 60


def validate_competitor_monitoring_settings(payload: object) -> dict[str, object]:
    expected = set(COMPETITOR_MONITORING_SETTINGS) | set(AUTO_COLLECTION_SETTINGS)
    if not isinstance(payload, dict) or set(payload) != expected:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "invalid_competitor_monitoring_settings", "message": "必须完整提交竞品监控设置"})
    values: dict[str, object] = {}
    for field, (_key, _default, minimum, maximum, minute_multiple) in COMPETITOR_MONITORING_SETTINGS.items():
        value = payload[field]
        if not _valid_monitoring_value(value, minimum, maximum, minute_multiple):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "invalid_competitor_monitoring_settings", "field": field, "message": f"{field} 参数无效"})
        values[field] = value
    if type(payload["auto_collection_enabled"]) is not bool:
        raise HTTPException(status_code=422, detail={"code": "invalid_competitor_monitoring_settings", "field": "auto_collection_enabled", "message": "auto_collection_enabled 参数无效"})
    if not isinstance(payload["auto_collection_strategy"], str) or payload["auto_collection_strategy"] not in {"rolling_24h", "fixed_daily", "fixed_interval"}:
        raise HTTPException(status_code=422, detail={"code": "invalid_competitor_monitoring_settings", "field": "auto_collection_strategy", "message": "auto_collection_strategy 参数无效"})
    if not isinstance(payload["auto_collection_time"], str) or _TIME_PATTERN.fullmatch(payload["auto_collection_time"]) is None:
        raise HTTPException(status_code=422, detail={"code": "invalid_competitor_monitoring_settings", "field": "auto_collection_time", "message": "auto_collection_time 参数无效"})
    if not _valid_times(payload["auto_collection_times"]):
        raise HTTPException(status_code=422, detail={"code": "invalid_competitor_monitoring_settings", "field": "auto_collection_times", "message": "每日时间点须为 1–8 个不重复的 HH:mm"})
    values["auto_collection_times"] = sorted(payload["auto_collection_times"])
    for field, minimum, maximum in (("auto_collection_interval_hours", 1, 24), ("auto_collection_daily_limit", 1, 12)):
        value = payload[field]
        if type(value) is not int or not minimum <= value <= maximum:
            raise HTTPException(status_code=422, detail={"code": "invalid_competitor_monitoring_settings", "field": field, "message": f"{field} 参数无效"})
        values[field] = value
    if payload["auto_collection_strategy"] == "fixed_daily" and payload["auto_collection_time"] != values["auto_collection_times"][0]:
        raise HTTPException(status_code=422, detail={"code": "invalid_competitor_monitoring_settings", "field": "auto_collection_time", "message": "须与每日最早时间点一致"})
    if payload["auto_collection_strategy"] == "fixed_interval" and not _valid_interval(payload["auto_collection_time"], values["auto_collection_interval_hours"], values["auto_collection_daily_limit"]):
        raise HTTPException(status_code=422, detail={"code": "invalid_competitor_monitoring_settings", "field": "auto_collection_daily_limit", "message": "固定间隔计划必须全部落在同一天内"})
    if not isinstance(payload["auto_collection_missed_policy"], str) or payload["auto_collection_missed_policy"] not in {"catch_up", "skip"}:
        raise HTTPException(status_code=422, detail={"code": "invalid_competitor_monitoring_settings", "field": "auto_collection_missed_policy", "message": "auto_collection_missed_policy 参数无效"})
    values.update({field: values.get(field, payload[field]) for field in AUTO_COLLECTION_SETTINGS})
    return values


def batch_config_values(settings: dict[str, object]) -> dict[str, int]:
    """Explicitly keep scheduler-only values out of BatchConfig."""
    return {field: int(settings[field]) for field in COMPETITOR_MONITORING_SETTINGS}


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
def get_competitor_monitoring_setting(db: Session = Depends(get_db)) -> dict[str, object]:
    return get_competitor_monitoring_settings(db)


@router.put("/competitor-monitoring")
def update_competitor_monitoring_setting(
    payload: object = Body(...), db: Session = Depends(get_db)
) -> dict[str, object]:
    values = validate_competitor_monitoring_settings(payload)
    try:
        for field, (key, _default, _minimum, _maximum, _minute_multiple) in COMPETITOR_MONITORING_SETTINGS.items():
            setting = db.get(SystemSetting, key)
            if setting is None:
                db.add(SystemSetting(key=key, value=str(values[field])))
            else:
                setting.value = str(values[field])
        for field, (key, _default) in AUTO_COLLECTION_SETTINGS.items():
            setting = db.get(SystemSetting, key)
            encoded = "true" if values[field] is True else "false" if values[field] is False else json.dumps(values[field], separators=(",", ":")) if field == "auto_collection_times" else str(values[field])
            if setting is None:
                db.add(SystemSetting(key=key, value=encoded))
            else:
                setting.value = encoded
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail={"code": "competitor_monitoring_settings_save_failed", "message": "竞品监控设置保存失败"}) from exc
    return values
