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
from app.models import Base, Competitor


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


def test_adds_competitor_and_normalizes_url(client: tuple[TestClient, sessionmaker[Session]]) -> None:
    test_client, session_factory = client

    response = test_client.post(
        "/api/competitors",
        json={"url": "https://detail.1688.com/offer/123456789.html?spm=abc#top"},
    )

    assert response.status_code == 201
    assert response.json()["platform"] == "1688"
    assert response.json()["offer_id"] == "123456789"
    assert response.json()["url"] == "https://detail.1688.com/offer/123456789.html"
    assert response.json()["group_id"] is None
    assert response.json()["status"] == "unknown"
    assert response.json()["is_active"] is True

    with session_factory() as session:
        competitors = session.scalars(select(Competitor)).all()
        assert len(competitors) == 1
        assert competitors[0].offer_id == "123456789"


def test_lists_empty_competitors(client: tuple[TestClient, sessionmaker[Session]]) -> None:
    response = client[0].get("/api/competitors")

    assert response.status_code == 200
    assert response.json() == []


def test_lists_all_competitors_in_created_at_and_id_desc_order(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    with session_factory() as session:
        session.add_all(
            [
                Competitor(
                    platform="1688",
                    offer_id="111",
                    url="https://detail.1688.com/offer/111.html",
                    title="older",
                    status="unknown",
                    is_active=True,
                    created_at=datetime(2026, 9, 18, tzinfo=timezone.utc),
                    updated_at=datetime(2026, 9, 18, tzinfo=timezone.utc),
                ),
                Competitor(
                    platform="1688",
                    offer_id="222",
                    url="https://detail.1688.com/offer/222.html",
                    title="newer low id",
                    status="active",
                    is_active=True,
                    created_at=datetime(2026, 9, 19, tzinfo=timezone.utc),
                    updated_at=datetime(2026, 9, 19, tzinfo=timezone.utc),
                ),
                Competitor(
                    platform="1688",
                    offer_id="333",
                    url="https://detail.1688.com/offer/333.html",
                    status="offline",
                    is_active=False,
                    created_at=datetime(2026, 9, 19, tzinfo=timezone.utc),
                    updated_at=datetime(2026, 9, 19, tzinfo=timezone.utc),
                ),
            ]
        )
        session.commit()

    response = test_client.get("/api/competitors")

    assert response.status_code == 200
    body = response.json()
    assert [item["offer_id"] for item in body] == ["333", "222", "111"]
    assert set(body[0]) == {
        "id",
        "platform",
        "offer_id",
        "url",
        "title",
        "shop_name",
        "main_image_url",
        "status",
        "is_active",
        "created_at",
        "last_collected_at",
        "latest_snapshot",
    }


def test_listing_does_not_trigger_collection_side_effects(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    response = client[0].get("/api/competitors")

    assert response.status_code == 200
    with client[1]() as session:
        assert session.query(Competitor).count() == 0


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://detail.1688.com/offer/123456789.html",
        "https://m.1688.com/offer/123456789.html",
        "https://detail.1688.com/page/123456789.html",
        "https://detail.1688.com/offer/not-numeric.html",
        "https://user:pass@detail.1688.com/offer/123456789.html",
        "https://detail.1688.com:8443/offer/123456789.html",
    ],
)
def test_rejects_invalid_1688_url(
    client: tuple[TestClient, sessionmaker[Session]], url: str
) -> None:
    response = client[0].post("/api/competitors", json={"url": url})

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_competitor_url"


def test_non_null_group_id_is_out_of_scope(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    response = client[0].post(
        "/api/competitors",
        json={"url": "https://detail.1688.com/offer/123456789.html", "group_id": 1},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "group_not_supported"


def test_duplicate_offer_id_returns_409_without_new_record(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    url = "https://detail.1688.com/offer/123456789.html"

    assert test_client.post("/api/competitors", json={"url": url}).status_code == 201
    response = test_client.post(
        "/api/competitors",
        json={"url": f"{url}?spm=another"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "competitor_already_exists"
    with session_factory() as session:
        assert len(session.scalars(select(Competitor)).all()) == 1


def test_status_constraint_rejects_unknown_value(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    _, session_factory = client
    with session_factory() as session:
        session.add(
            Competitor(
                platform="1688",
                offer_id="987654321",
                url="https://detail.1688.com/offer/987654321.html",
                status="invalid",
                is_active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
