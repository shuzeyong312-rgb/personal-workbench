from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, ChangeEvent, Competitor, ProductSnapshot


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


def snapshot(session: Session, item: Competitor) -> ProductSnapshot:
    value = ProductSnapshot(
        competitor_id=item.id,
        captured_at=datetime(2026, 9, 19, tzinfo=timezone.utc),
        title="商品标题",
        shop_name="店铺",
        product_status="unknown",
        collection_source="html",
    )
    session.add(value)
    session.flush()
    return value


def test_change_event_stores_product_change_values(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        item = competitor()
        session.add(item)
        session.flush()
        product_snapshot = snapshot(session, item)
        detected_at = datetime(2026, 9, 19, 12, 30, tzinfo=timezone.utc)
        session.add(
            ChangeEvent(
                competitor_id=item.id,
                snapshot_id=product_snapshot.id,
                change_type="price_increase",
                entity_key=None,
                old_value="40.00",
                new_value="45.00",
                detected_at=detected_at,
            )
        )
        session.commit()

        saved = session.scalar(select(ChangeEvent))
        assert saved is not None
        assert saved.competitor_id == item.id
        assert saved.snapshot_id == product_snapshot.id
        assert saved.change_type == "price_increase"
        assert saved.entity_key is None
        assert saved.old_value == "40.00"
        assert saved.new_value == "45.00"
        assert saved.detected_at == detected_at.replace(tzinfo=None)


def test_change_event_preserves_zero_stock_as_a_string(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        item = competitor()
        session.add(item)
        session.flush()
        product_snapshot = snapshot(session, item)
        session.add(
            ChangeEvent(
                competitor_id=item.id,
                snapshot_id=product_snapshot.id,
                change_type="stock_changed",
                entity_key="sku-1",
                old_value="0",
                new_value="10",
                detected_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

        saved = session.scalar(select(ChangeEvent))
        assert saved is not None
        assert saved.entity_key == "sku-1"
        assert saved.old_value == "0"
        assert saved.new_value == "10"


def test_change_event_rejects_unsupported_change_type(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        item = competitor()
        session.add(item)
        session.flush()
        product_snapshot = snapshot(session, item)
        session.add(
            ChangeEvent(
                competitor_id=item.id,
                snapshot_id=product_snapshot.id,
                change_type="sales_increase",
                detected_at=datetime.now(timezone.utc),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_change_event_rejects_unknown_competitor(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        item = competitor()
        session.add(item)
        session.flush()
        product_snapshot = snapshot(session, item)
        session.add(
            ChangeEvent(
                competitor_id=999,
                snapshot_id=product_snapshot.id,
                change_type="price_increase",
                detected_at=datetime.now(timezone.utc),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_change_event_rejects_unknown_snapshot(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        item = competitor()
        session.add(item)
        session.flush()
        session.add(
            ChangeEvent(
                competitor_id=item.id,
                snapshot_id=999,
                change_type="price_increase",
                detected_at=datetime.now(timezone.utc),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_change_event_values_are_nullable_for_sku_add_and_remove(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        item = competitor()
        session.add(item)
        session.flush()
        product_snapshot = snapshot(session, item)
        detected_at = datetime.now(timezone.utc)
        session.add_all(
            [
                ChangeEvent(
                    competitor_id=item.id,
                    snapshot_id=product_snapshot.id,
                    change_type="sku_added",
                    entity_key="sku-added",
                    old_value=None,
                    new_value="新规格",
                    detected_at=detected_at,
                ),
                ChangeEvent(
                    competitor_id=item.id,
                    snapshot_id=product_snapshot.id,
                    change_type="sku_removed",
                    entity_key="sku-removed",
                    old_value="旧规格",
                    new_value=None,
                    detected_at=detected_at,
                ),
            ]
        )
        session.commit()

        saved = session.scalars(select(ChangeEvent).order_by(ChangeEvent.id)).all()
        assert [(event.old_value, event.new_value) for event in saved] == [
            (None, "新规格"),
            ("旧规格", None),
        ]
