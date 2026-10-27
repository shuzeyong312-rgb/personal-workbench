from urllib.parse import urlsplit, urlunsplit
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, StrictBool
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ToolboxItem

router = APIRouter(prefix="/api/toolbox", tags=["toolbox"])


class SiteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    url: str
    category: str = ""
    description: str = ""


class FavoriteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    favorite: StrictBool


def failure(code: str, message: str, status: int):
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def normalize_url(value: str) -> str:
    value = value.strip()
    try:
        if not value or len(value) > 2048 or any(ord(c) < 33 or ord(c) == 127 for c in value) or "\\" in value:
            raise ValueError()
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError()
        host = parsed.hostname.encode("idna").decode("ascii").lower()
        if ":" in host:
            host = f"[{host}]"
        port = parsed.port
        if port is not None and not ((parsed.scheme.lower() == "http" and port == 80) or (parsed.scheme.lower() == "https" and port == 443)):
            host += f":{port}"
        path = "/".join(re.sub(r"%2e", ".", segment, flags=re.IGNORECASE) if re.fullmatch(r"(?:\.|%2e){1,2}", segment, flags=re.IGNORECASE) else segment for segment in parsed.path.split("/"))
        result = str(httpx.URL(urlunsplit((parsed.scheme.lower(), host, path or "/", parsed.query, parsed.fragment))))
        if len(result) > 2048:
            raise ValueError()
        return result
    except (ValueError, UnicodeError, httpx.InvalidURL):
        raise failure("invalid_url", "请输入有效的 HTTP 或 HTTPS 网址", 400)


def serialize(item: ToolboxItem):
    return {key: getattr(item, key) for key in ("id", "kind", "builtin_key", "name", "category", "description", "url", "favorite")}


def get_item(db: Session, item_id: int) -> ToolboxItem:
    item = db.get(ToolboxItem, item_id)
    if item is None:
        raise failure("not_found", "工具不存在", 404)
    return item


def save_site(db: Session, payload: SiteInput, item: ToolboxItem):
    name, category, description = payload.name.strip(), payload.category.strip(), payload.description.strip()
    if not name or len(name) > 100 or len(category) > 50 or len(description) > 200:
        raise failure("invalid_site", "名称或其他字段长度无效", 400)
    url = normalize_url(payload.url)
    name_key = name.casefold()
    for field, value, code, message in ((ToolboxItem.name_key, name_key, "duplicate_name", "名称已存在"), (ToolboxItem.url, url, "duplicate_url", "网址已存在")):
        if db.scalar(select(ToolboxItem.id).where(field == value, ToolboxItem.id != (item.id or 0))) is not None:
            raise failure(code, message, 409)
    item.name, item.name_key, item.category, item.description, item.url = name, name_key, category, description, url
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if db.scalar(select(ToolboxItem.id).where(ToolboxItem.name_key == name_key, ToolboxItem.id != (item.id or 0))) is not None:
            raise failure("duplicate_name", "名称已存在", 409)
        raise failure("duplicate_url", "网址已存在", 409)
    db.refresh(item)
    return serialize(item)


@router.get("/items")
def list_items(db: Session = Depends(get_db)):
    try:
        return [serialize(item) for item in db.scalars(select(ToolboxItem).order_by(ToolboxItem.id))]
    except OperationalError as exc:
        if "no such table: toolbox_items" in str(exc.orig):
            raise failure("toolbox_migration_required", "工具箱数据库尚未升级，请重启工作台以执行数据库迁移", 503)
        raise


@router.post("/sites", status_code=201)
def create_site(payload: SiteInput, db: Session = Depends(get_db)):
    return save_site(db, payload, ToolboxItem(kind="site", favorite=False))


@router.patch("/sites/{item_id}")
def update_site(item_id: int, payload: SiteInput, db: Session = Depends(get_db)):
    item = get_item(db, item_id)
    if item.kind != "site":
        raise failure("builtin_protected", "内置工具不可编辑", 403)
    return save_site(db, payload, item)


@router.delete("/sites/{item_id}", status_code=204)
def delete_site(item_id: int, db: Session = Depends(get_db)):
    item = get_item(db, item_id)
    if item.kind != "site":
        raise failure("builtin_protected", "内置工具不可删除", 403)
    db.delete(item)
    db.commit()


@router.patch("/items/{item_id}/favorite")
def favorite_item(item_id: int, payload: FavoriteInput, db: Session = Depends(get_db)):
    item = get_item(db, item_id)
    item.favorite = payload.favorite
    db.commit()
    return serialize(item)
