from collections.abc import Generator
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, CollectionRun, Competitor, ProductSnapshot, SkuSnapshot


@pytest.fixture()
def session_factory() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


def competitor() -> Competitor:
    now = datetime.now(timezone.utc)
    return Competitor(
        platform="1688",
        offer_id="123456789",
        url="https://detail.1688.com/offer/123456789.html",
        status="unknown",
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def test_snapshots_and_collection_runs_store_required_values(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        item = competitor()
        session.add(item)
        session.flush()
        captured_at = datetime(2026, 9, 19, tzinfo=timezone.utc)
        snapshot = ProductSnapshot(
            competitor_id=item.id,
            captured_at=captured_at,
            title="商品标题",
            shop_name="店铺",
            main_image_url=None,
            price_min=Decimal("12.30"),
            price_max=Decimal("18.60"),
            product_status="active",
            collection_source="html",
            skus=[
                SkuSnapshot(sku_id="sku-1", sku_name="红色", stock=None, price=None),
                SkuSnapshot(
                    sku_id="sku-2",
                    sku_name="蓝色",
                    stock=7,
                    price=Decimal("15.20"),
                ),
            ],
        )
        running = CollectionRun(
            competitor_id=item.id,
            started_at=captured_at,
            finished_at=None,
            status="running",
        )
        success = CollectionRun(
            competitor_id=item.id,
            started_at=captured_at,
            finished_at=captured_at,
            status="success",
        )
        failed = CollectionRun(
            competitor_id=item.id,
            started_at=captured_at,
            finished_at=captured_at,
            status="failed",
            error_type="collection_timeout",
            error_message="采集超时",
        )
        session.add_all([snapshot, running, success, failed])
        session.commit()

        saved_snapshot = session.scalar(select(ProductSnapshot))
        assert saved_snapshot is not None
        assert len(saved_snapshot.skus) == 2
        assert saved_snapshot.price_min == Decimal("12.30")
        assert isinstance(saved_snapshot.price_min, Decimal)
        assert session.scalar(select(SkuSnapshot).where(SkuSnapshot.stock.is_(None))) is not None
        assert session.scalar(select(CollectionRun).where(CollectionRun.status == "running")) is not None
        assert {run.status for run in session.scalars(select(CollectionRun))} == {
            "running",
            "success",
            "failed",
        }


def test_foreign_keys_are_enforced_and_sku_rows_cascade(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        assert session.connection().exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1

        session.add(
            ProductSnapshot(
                competitor_id=999,
                captured_at=datetime.now(timezone.utc),
                title="商品标题",
                shop_name="店铺",
                product_status="unknown",
                collection_source="html",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        item = competitor()
        session.add(item)
        session.flush()
        snapshot = ProductSnapshot(
            competitor_id=item.id,
            captured_at=datetime.now(timezone.utc),
            title="商品标题",
            shop_name="店铺",
            product_status="unknown",
            collection_source="html",
            skus=[SkuSnapshot(sku_id="sku-1", sku_name="红色")],
        )
        session.add(snapshot)
        session.commit()
        session.execute(delete(ProductSnapshot).where(ProductSnapshot.id == snapshot.id))
        session.commit()

        assert session.scalar(select(SkuSnapshot).where(SkuSnapshot.sku_id == "sku-1")) is None


@pytest.mark.parametrize(
    ("model", "field", "value"),
    [
        (ProductSnapshot, "product_status", "invalid"),
        (ProductSnapshot, "collection_source", "plugin_api"),
        (CollectionRun, "status", "pending"),
    ],
)
def test_enum_checks_are_enforced_by_sqlite(
    session_factory: sessionmaker[Session], model: type[ProductSnapshot | CollectionRun], field: str, value: str
) -> None:
    with session_factory() as session:
        item = competitor()
        session.add(item)
        session.flush()
        common = {
            "competitor_id": item.id,
            "captured_at": datetime.now(timezone.utc),
            "title": "商品标题",
            "shop_name": "店铺",
            "product_status": "active",
            "collection_source": "html",
        }
        entity = ProductSnapshot(**common) if model is ProductSnapshot else CollectionRun(
            competitor_id=item.id,
            started_at=datetime.now(timezone.utc),
            status="running",
        )
        setattr(entity, field, value)
        session.add(entity)
        with pytest.raises(IntegrityError):
            session.commit()
