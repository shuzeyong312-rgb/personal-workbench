from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import SystemSetting
from app.ownership import MAX_OWN_SHOP_NAME_LENGTH, OWN_SHOP_NAME_KEY, get_own_shop_name, normalize_shop_name, reconcile_ownership


router = APIRouter(prefix="/api/settings", tags=["settings"])


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
