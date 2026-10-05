from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import app
from app.models import Base, CollectionRun, Competitor


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


def add_competitor(
    session: Session,
    competitor_id: int,
    *,
    ownership: str = "competitor",
    title: str | None = None,
    offer_id: str | None = None,
    shop_name: str | None = None,
) -> Competitor:
    now = datetime(2026, 10, 5, tzinfo=timezone.utc)
    competitor = Competitor(
        id=competitor_id,
        platform="1688",
        offer_id=offer_id or f"offer-{competitor_id}",
        url=f"https://detail.1688.com/offer/{competitor_id}.html",
        title=title or f"商品 {competitor_id}",
        shop_name=shop_name or f"店铺 {competitor_id}",
        main_image_url=None,
        status="active",
        is_active=True,
        ownership=ownership,
        group_role="competitor",
        created_at=now,
        updated_at=now,
    )
    session.add(competitor)
    session.flush()
    return competitor


def add_run(
    session: Session,
    run_id: int,
    competitor_id: int,
    *,
    started_at: datetime,
    status: str = "success",
    finished_at: datetime | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
) -> CollectionRun:
    run = CollectionRun(
        id=run_id,
        competitor_id=competitor_id,
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        error_type=error_type,
        error_message=error_message,
    )
    session.add(run)
    session.flush()
    return run


def test_collection_runs_defaults_to_descending_started_at_and_fixed_pagination(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    started = datetime(2026, 10, 5, tzinfo=timezone.utc)
    with session_factory() as session:
        add_competitor(session, 1)
        add_competitor(session, 2)
        add_competitor(session, 3)
        add_run(session, 10, 1, started_at=started)
        add_run(session, 11, 2, started_at=started)
        add_run(session, 12, 3, started_at=started + timedelta(minutes=1))
        session.commit()

    response = test_client.get("/api/collection-runs")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert [item["id"] for item in body["items"]] == [12, 11, 10]
    assert body["items"][0]["title"] == "商品 3"


def test_collection_runs_filters_by_status_ownership_and_current_product_search(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    started = datetime(2026, 10, 5, tzinfo=timezone.utc)
    with session_factory() as session:
        own = add_competitor(session, 1, ownership="self", title="自营暖手宝", offer_id="self-offer", shop_name="我方店铺")
        competitor = add_competitor(session, 2, title="竞品暖手宝", offer_id="rival-offer", shop_name="竞品店铺")
        add_run(session, 1, own.id, started_at=started, status="success", finished_at=started + timedelta(seconds=12))
        add_run(session, 2, competitor.id, started_at=started + timedelta(minutes=1), status="failed", finished_at=started + timedelta(minutes=1, seconds=3), error_type="collection_timeout", error_message="商品页面加载超时")
        session.commit()

    failed = test_client.get("/api/collection-runs?status=failed&ownership=competitor")
    by_title = test_client.get("/api/collection-runs?search=%E6%9A%96%E6%89%8B%E5%AE%9D")
    by_offer = test_client.get("/api/collection-runs?search=self-offer")
    by_shop = test_client.get("/api/collection-runs?search=%E6%88%91%E6%96%B9%E5%BA%97%E9%93%BA")

    assert [item["id"] for item in failed.json()["items"]] == [2]
    assert failed.json()["items"][0]["error_message"] == "商品页面加载超时"
    assert [item["id"] for item in by_title.json()["items"]] == [2, 1]
    assert [item["id"] for item in by_offer.json()["items"]] == [1]
    assert [item["id"] for item in by_shop.json()["items"]] == [1]


def test_collection_runs_validates_params_and_keeps_out_of_range_page(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    with session_factory() as session:
        competitor = add_competitor(session, 1)
        add_run(session, 1, competitor.id, started_at=datetime(2026, 10, 5, tzinfo=timezone.utc))
        session.commit()

    assert test_client.get("/api/collection-runs?status=running").status_code == 422
    assert test_client.get("/api/collection-runs?ownership=unknown").status_code == 422
    assert test_client.get("/api/collection-runs?page=0").status_code == 422
    out_of_range = test_client.get("/api/collection-runs?page=9")

    assert out_of_range.status_code == 200
    assert out_of_range.json() == {"items": [], "total": 1, "page": 9, "page_size": 20}


def test_collection_runs_reports_nonnegative_duration_running_null_and_does_not_mutate(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    started = datetime(2026, 10, 5, tzinfo=timezone.utc)
    with session_factory() as session:
        competitor = add_competitor(session, 1)
        add_run(session, 1, competitor.id, started_at=started, finished_at=started - timedelta(seconds=2))
        add_run(session, 2, competitor.id, started_at=started + timedelta(minutes=1), status="running")
        session.commit()

    response = test_client.get("/api/collection-runs?search=%20%20")

    assert response.status_code == 200
    assert response.json()["items"][0]["status"] == "running"
    assert response.json()["items"][0]["duration_seconds"] is None
    assert response.json()["items"][1]["duration_seconds"] == 0
    with session_factory() as session:
        assert session.scalars(select(CollectionRun).order_by(CollectionRun.id)).all()[0].finished_at == (started - timedelta(seconds=2)).replace(tzinfo=None)
        assert session.query(CollectionRun).count() == 2


def test_combined_filters_count_before_paging_and_preserve_order_and_empty_page(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    started = datetime(2026, 10, 5, tzinfo=timezone.utc)
    with session_factory() as session:
        # Each search column participates; distractors differ on one filter at a time.
        add_competitor(session, 1, ownership="self", title="target 标题")
        add_competitor(session, 2, ownership="self", offer_id="target-offer")
        add_competitor(session, 3, ownership="self", shop_name="target 店铺")
        add_competitor(session, 4, ownership="competitor", title="target 竞品")
        add_competitor(session, 5, ownership="self", title="无关商品")
        for run_id in range(1, 26):
            add_run(session, run_id, (run_id % 3) + 1,
                    started_at=started + timedelta(minutes=run_id // 2), status="failed")
        for run_id in range(26, 66):
            product_id, status = [(4, "failed"), (5, "failed"), (1, "success"), (2, "running")][run_id % 4]
            add_run(session, run_id, product_id,
                    started_at=started + timedelta(days=1), status=status)
        session.commit()

    params = {"search": " target ", "status": "failed", "ownership": "self"}
    first = test_client.get("/api/collection-runs", params={**params, "page": 1})
    second = test_client.get("/api/collection-runs", params={**params, "page": 2})
    empty = test_client.get("/api/collection-runs", params={**params, "page": 3})
    assert first.status_code == second.status_code == empty.status_code == 200
    assert first.json()["total"] == second.json()["total"] == 25
    assert first.json()["page_size"] == second.json()["page_size"] == 20
    assert [item["id"] for item in first.json()["items"]] == list(range(25, 5, -1))
    assert [item["id"] for item in second.json()["items"]] == [5, 4, 3, 2, 1]
    assert second.json()["page"] == 2
    assert empty.json() == {"items": [], "total": 25, "page": 3, "page_size": 20}
