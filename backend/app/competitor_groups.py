from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.competitors import error
from app.database import get_db
from app.models import CompetitorGroup


router = APIRouter(prefix="/api/competitor-groups", tags=["competitor-groups"])


class CreateCompetitorGroupRequest(BaseModel):
    name: str


class CompetitorGroupResponse(BaseModel):
    id: int
    name: str
    created_at: datetime


@router.post("", response_model=CompetitorGroupResponse, status_code=status.HTTP_201_CREATED)
def create_competitor_group(
    payload: CreateCompetitorGroupRequest, db: Session = Depends(get_db)
) -> CompetitorGroup:
    name = payload.name.strip()
    if not name or len(name) > 64:
        raise error(
            "invalid_competitor_group_name",
            "请输入有效的竞品组名称",
            status.HTTP_400_BAD_REQUEST,
        )

    group = CompetitorGroup(name=name, created_at=datetime.now(timezone.utc))
    db.add(group)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise error(
            "competitor_group_already_exists",
            "该竞品组已存在",
            status.HTTP_409_CONFLICT,
        ) from exc
    db.refresh(group)
    return group


@router.get("", response_model=list[CompetitorGroupResponse])
def list_competitor_groups(db: Session = Depends(get_db)) -> list[CompetitorGroup]:
    return list(
        db.scalars(
            select(CompetitorGroup).order_by(CompetitorGroup.created_at.asc(), CompetitorGroup.id.asc())
        ).all()
    )
