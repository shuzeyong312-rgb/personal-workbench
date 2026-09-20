from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import app
from app.models import Base, Competitor, CompetitorGroup


@pytest.fixture()
def client() -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client, session_factory
    app.dependency_overrides.clear()
    engine.dispose()


def test_creates_group_with_trimmed_name(client: tuple[TestClient, sessionmaker[Session]]) -> None:
    response = client[0].post("/api/competitor-groups", json={"name": "  暖手宝  "})

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "暖手宝"
    assert set(body) == {"id", "name", "created_at"}


@pytest.mark.parametrize("name", ["", "   ", "a" * 65])
def test_rejects_invalid_group_name(
    client: tuple[TestClient, sessionmaker[Session]], name: str
) -> None:
    response = client[0].post("/api/competitor-groups", json={"name": name})

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_competitor_group_name"


def test_duplicate_group_name_returns_conflict(client: tuple[TestClient, sessionmaker[Session]]) -> None:
    test_client = client[0]
    assert test_client.post("/api/competitor-groups", json={"name": "暖手宝"}).status_code == 201

    response = test_client.post("/api/competitor-groups", json={"name": "  暖手宝 "})

    assert response.status_code == 409
    assert response.json()["code"] == "competitor_group_already_exists"


def test_group_name_unique_constraint_is_enforced_by_database(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    with client[1]() as session:
        now = datetime.now(timezone.utc)
        session.add(CompetitorGroup(name="暖手宝", created_at=now))
        session.commit()
        session.add(CompetitorGroup(name="暖手宝", created_at=now))
        with pytest.raises(IntegrityError):
            session.commit()


def test_lists_groups_in_created_at_and_id_ascending_order(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    timestamp = datetime(2026, 9, 20, 10, tzinfo=timezone.utc)
    with client[1]() as session:
        session.add_all(
            [
                CompetitorGroup(name="第二组", created_at=timestamp),
                CompetitorGroup(name="第一组", created_at=timestamp),
            ]
        )
        session.commit()
        expected_names = [group.name for group in session.scalars(
            select(CompetitorGroup).order_by(CompetitorGroup.created_at, CompetitorGroup.id)
        ).all()]

    response = client[0].get("/api/competitor-groups")

    assert response.status_code == 200
    assert [item["name"] for item in response.json()] == expected_names


def test_competitor_group_foreign_key_is_enforced(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    with client[1]() as session:
        session.add(
            Competitor(
                group_id=999,
                platform="1688",
                offer_id="123456789",
                url="https://detail.1688.com/offer/123456789.html",
                status="unknown",
                is_active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
