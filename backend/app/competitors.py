import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Competitor


router = APIRouter(prefix="/api/competitors", tags=["competitors"])
OFFER_PATH = re.compile(r"^/offer/(\d+)\.html$")


class CreateCompetitorRequest(BaseModel):
    url: str
    group_id: int | None = None


class CompetitorResponse(BaseModel):
    id: int
    platform: str
    offer_id: str
    url: str
    group_id: int | None
    status: str
    is_active: bool
    created_at: datetime


class CompetitorListResponse(BaseModel):
    id: int
    platform: str
    offer_id: str
    url: str
    title: str | None
    shop_name: str | None
    main_image_url: str | None
    status: str
    is_active: bool
    created_at: datetime
    last_collected_at: datetime | None


def parse_1688_url(url: str) -> tuple[str, str]:
    value = url.strip()
    if not value:
        raise ValueError("invalid competitor url")

    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "detail.1688.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
    ):
        raise ValueError("invalid competitor url")

    match = OFFER_PATH.fullmatch(parsed.path)
    if not match:
        raise ValueError("invalid competitor url")

    offer_id = match.group(1)
    return offer_id, f"https://detail.1688.com/offer/{offer_id}.html"


def error(code: str, message: str, status_code: int) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


@router.get("", response_model=list[CompetitorListResponse])
def list_competitors(db: Session = Depends(get_db)) -> list[Competitor]:
    return list(
        db.scalars(
            select(Competitor).order_by(
                Competitor.created_at.desc(),
                Competitor.id.desc(),
            )
        ).all()
    )


@router.post("", response_model=CompetitorResponse, status_code=status.HTTP_201_CREATED)
def create_competitor(payload: CreateCompetitorRequest, db: Session = Depends(get_db)) -> Competitor:
    try:
        offer_id, normalized_url = parse_1688_url(payload.url)
    except ValueError as exc:
        raise error(
            "invalid_competitor_url",
            "仅支持 https://detail.1688.com/offer/{offerId}.html 格式的 1688 商品链接",
            status.HTTP_400_BAD_REQUEST,
        ) from exc

    if payload.group_id is not None:
        raise error("group_not_supported", "当前暂不支持指定竞品组", status.HTTP_400_BAD_REQUEST)

    if db.scalar(select(Competitor).where(Competitor.platform == "1688", Competitor.offer_id == offer_id)):
        raise error("competitor_already_exists", "该 1688 商品已经添加", status.HTTP_409_CONFLICT)

    now = datetime.now(timezone.utc)
    competitor = Competitor(
        platform="1688",
        offer_id=offer_id,
        url=normalized_url,
        group_id=None,
        status="unknown",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(competitor)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(Competitor).where(
                Competitor.platform == "1688",
                Competitor.offer_id == offer_id,
            )
        )
        if existing:
            raise error("competitor_already_exists", "该 1688 商品已经添加", status.HTTP_409_CONFLICT)
        raise
    db.refresh(competitor)
    return competitor
