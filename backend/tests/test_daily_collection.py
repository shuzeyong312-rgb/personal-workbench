from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from threading import RLock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.collection import daily
from app.collection.daily import run_daily_collection_cycle
from app.collection.service import CollectionError, CollectionInProgressError
from app.models import Base, CollectionRun, Competitor


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


NOW = datetime(2026, 9, 20, 0, tzinfo=timezone.utc)


def add_competitor(factory: sessionmaker[Session], *, active: bool = True) -> int:
    with factory() as session:
        competitor = Competitor(
            platform="1688",
            offer_id=str(100 + session.query(Competitor).count()),
            url="https://detail.1688.com/offer/test.html",
            status="unknown",
            is_active=active,
            created_at=NOW,
            updated_at=NOW,
        )
        session.add(competitor)
        session.commit()
        return competitor.id


def add_run(
    factory: sessionmaker[Session], competitor_id: int, started_at: datetime, status: str
) -> None:
    with factory() as session:
        session.add(
            CollectionRun(
                competitor_id=competitor_id,
                started_at=started_at,
                finished_at=started_at,
                status=status,
            )
        )
        session.commit()


def test_first_collection_is_due_and_collected(session_factory: sessionmaker[Session]) -> None:
    competitor_id = add_competitor(session_factory)
    calls: list[int] = []

    result = run_daily_collection_cycle(
        session_factory,
        now=NOW,
        collect=lambda _session, item_id: calls.append(item_id),
    )

    assert calls == [competitor_id]
    assert result.due == 1
    assert result.success == 1
    assert result.failed == result.skipped == result.interrupted == 0


def test_recent_run_is_skipped(session_factory: sessionmaker[Session]) -> None:
    competitor_id = add_competitor(session_factory)
    add_run(session_factory, competitor_id, NOW - timedelta(hours=23, minutes=59), "success")
    calls: list[int] = []

    result = run_daily_collection_cycle(
        session_factory,
        now=NOW,
        collect=lambda _session, item_id: calls.append(item_id),
    )

    assert calls == []
    assert result.due == 0
    assert result.skipped == 1


@pytest.mark.parametrize("status", ["success", "failed"])
def test_run_at_least_24_hours_ago_is_due(
    session_factory: sessionmaker[Session], status: str
) -> None:
    competitor_id = add_competitor(session_factory)
    add_run(session_factory, competitor_id, NOW - timedelta(hours=24), status)
    calls: list[int] = []

    result = run_daily_collection_cycle(
        session_factory,
        now=NOW,
        collect=lambda _session, item_id: calls.append(item_id),
    )

    assert calls == [competitor_id]
    assert result.due == 1
    assert result.success == 1


def test_inactive_competitor_is_skipped(session_factory: sessionmaker[Session]) -> None:
    add_competitor(session_factory, active=False)
    calls: list[int] = []

    result = run_daily_collection_cycle(
        session_factory,
        now=NOW,
        collect=lambda _session, item_id: calls.append(item_id),
    )

    assert calls == []
    assert result.due == result.success == result.failed == 0
    assert result.skipped == 1


def test_due_competitors_are_collected_in_id_order(session_factory: sessionmaker[Session]) -> None:
    competitor_ids = [add_competitor(session_factory) for _ in range(3)]
    calls: list[int] = []

    run_daily_collection_cycle(
        session_factory,
        now=NOW,
        collect=lambda _session, item_id: calls.append(item_id),
    )

    assert calls == competitor_ids


def test_collection_error_does_not_stop_the_batch(session_factory: sessionmaker[Session]) -> None:
    competitor_ids = [add_competitor(session_factory) for _ in range(3)]
    calls: list[int] = []

    def collect(_session: Session, competitor_id: int) -> None:
        calls.append(competitor_id)
        if competitor_id == competitor_ids[1]:
            raise CollectionError("collection_timeout", "商品页面加载超时")

    result = run_daily_collection_cycle(session_factory, now=NOW, collect=collect)

    assert calls == competitor_ids
    assert result.due == 3
    assert result.success == 2
    assert result.failed == 1


def test_busy_collection_stops_the_cycle_without_failure(session_factory: sessionmaker[Session]) -> None:
    competitor_ids = [add_competitor(session_factory) for _ in range(2)]
    calls: list[int] = []

    def collect(_session: Session, competitor_id: int) -> None:
        calls.append(competitor_id)
        raise CollectionInProgressError

    result = run_daily_collection_cycle(session_factory, now=NOW, collect=collect)

    assert calls == [competitor_ids[0]]
    assert result.due == 1
    assert result.success == result.failed == 0
    assert result.interrupted == 1
    with session_factory() as session:
        assert session.scalars(select(CollectionRun)).all() == []


def test_naive_started_at_is_treated_as_utc(session_factory: sessionmaker[Session]) -> None:
    competitor_id = add_competitor(session_factory)
    add_run(session_factory, competitor_id, (NOW - timedelta(hours=24)).replace(tzinfo=None), "failed")

    result = run_daily_collection_cycle(
        session_factory,
        now=NOW,
        collect=lambda _session, _item_id: None,
    )

    assert result.due == 1


def test_candidate_rechecks_due_after_manual_collection_before_lock(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    competitor_id = add_competitor(session_factory)
    calls: list[int] = []

    class HookedLock:
        def __init__(self) -> None:
            self.real = RLock()
            self.hook = self._simulate_manual_collection

        def _simulate_manual_collection(self) -> None:
            self.real.acquire()
            try:
                add_run(session_factory, competitor_id, NOW - timedelta(hours=1), "success")
            finally:
                self.real.release()

        def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
            if self.hook is not None:
                hook = self.hook
                self.hook = None
                hook()
            if timeout == -1:
                return self.real.acquire(blocking)
            return self.real.acquire(blocking, timeout)

        def release(self) -> None:
            self.real.release()

    lock = HookedLock()
    monkeypatch.setattr(daily, "COLLECTION_LOCK", lock)

    def collect(_session: Session, item_id: int) -> None:
        assert lock.acquire(blocking=False)
        try:
            calls.append(item_id)
        finally:
            lock.release()

    result = run_daily_collection_cycle(session_factory, now=NOW, collect=collect)

    assert calls == []
    assert result.due == result.success == result.failed == 0
    assert result.skipped == 1
    with session_factory() as session:
        assert session.query(CollectionRun).count() == 1


def test_stop_event_stops_before_starting_next_competitor(
    session_factory: sessionmaker[Session],
) -> None:
    competitor_ids = [add_competitor(session_factory) for _ in range(2)]
    calls: list[int] = []
    from threading import Event

    stop_event = Event()

    def collect(_session: Session, item_id: int) -> None:
        calls.append(item_id)
        stop_event.set()

    result = run_daily_collection_cycle(
        session_factory,
        now=NOW,
        collect=collect,
        stop_event=stop_event,
    )

    assert calls == [competitor_ids[0]]
    assert result.due == result.success == 1
    assert result.failed == 0
    assert result.interrupted == 1
