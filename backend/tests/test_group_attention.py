from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models import ChangeEvent, Competitor, CompetitorGroup, ProductSnapshot, SkuSnapshot

from test_dashboard import END_UTC, START_UTC, client as client


def _competitor(session: Session, competitor_id: int, group_id: int, role: str) -> Competitor:
    now = datetime(2026, 9, 20, 1)
    value = Competitor(
        id=competitor_id, group_id=group_id, group_role=role, platform="1688",
        offer_id=str(competitor_id), url=f"https://example.com/{competitor_id}",
        title=f"商品 {competitor_id}", shop_name=f"店铺 {competitor_id}",
        status="active", is_active=True, created_at=now, updated_at=now,
    )
    session.add(value)
    session.flush()
    return value


def _event(session: Session, competitor: Competitor, kind: str, at: datetime, *, entity: str | None = None,
           delta_rate: float | None = None) -> None:
    snapshot_id = None
    if kind != "product_offline":
        snapshot = ProductSnapshot(
            competitor_id=competitor.id, captured_at=at, title=competitor.title or "",
            shop_name=competitor.shop_name or "", product_status="active", collection_source="html",
        )
        session.add(snapshot)
        session.flush()
        snapshot_id = snapshot.id
    session.add(ChangeEvent(
        competitor_id=competitor.id, snapshot_id=snapshot_id, change_type=kind,
        entity_key=entity, old_value="100", new_value="90", delta_rate=delta_rate,
        detected_at=at,
    ))


def _today(monkeypatch) -> None:
    import app.group_attention as attention

    monkeypatch.setattr(attention, "business_day_bounds", lambda: (datetime(2026, 9, 20).date(), START_UTC, END_UTC))


def test_group_attention_endpoint_returns_eligible_group_first_read_model(
    client: tuple[TestClient, sessionmaker[Session]], monkeypatch,
) -> None:
    _today(monkeypatch)
    with client[1]() as session:
        group = CompetitorGroup(id=1, name="A19", created_at=datetime(2026, 9, 1))
        unbound = CompetitorGroup(id=2, name="unbound", created_at=datetime(2026, 9, 1))
        session.add_all([group, unbound])
        session.flush()
        own = _competitor(session, 1, group.id, "own")
        price = _competitor(session, 2, group.id, "competitor")
        _competitor(session, 3, unbound.id, "competitor")
        _event(session, price, "price_decrease", datetime(2026, 9, 20, 1), delta_rate=-6)
        session.commit()

    response = client[0].get("/api/dashboard/group-attention")

    assert response.status_code == 200
    body = response.json()
    assert body["kpis"] == {
        "monitored_product_groups": 1,
        "changed_product_groups_today": 1,
        "changed_competitors_today": 1,
    }
    assert len(body["groups"]) == 1
    row = body["groups"][0]
    assert row["group_id"] == 1
    assert row["own_product"]["id"] == own.id
    assert row["attention_level"] == "重点关注"
    assert row["changed_competitor_count"] == 1
    assert row["reasons"][0]["reason_type"] == "price_decrease"
    assert len(row["reasons"]) <= 3
    assert "attention_score" not in row


def test_strong_discount_ranks_above_many_small_stock_changes_and_protects_levels(
    client: tuple[TestClient, sessionmaker[Session]], monkeypatch,
) -> None:
    _today(monkeypatch)
    with client[1]() as session:
        groups = [CompetitorGroup(id=i, name=f"G{i}", created_at=datetime(2026, 9, 1)) for i in range(1, 4)]
        session.add_all(groups)
        session.flush()
        for i, group in enumerate(groups, 1):
            _competitor(session, 100 + i, group.id, "own")
        sharp = _competitor(session, 201, 1, "competitor")
        _event(session, sharp, "price_decrease", datetime(2026, 9, 20, 1), delta_rate=-6)
        for i in range(5):
            competitor = _competitor(session, 210 + i, 2, "competitor")
            _event(session, competitor, "stock_decrease", datetime(2026, 9, 20, 2 + i), entity="s1")
        for i in range(8):
            competitor = _competitor(session, 220 + i, 3, "competitor")
            _event(session, competitor, "title_changed", datetime(2026, 9, 20, 8 + i))
        session.commit()

    body = client[0].get("/api/dashboard/group-attention").json()
    rows = {row["group_id"]: row for row in body["groups"]}

    assert body["groups"][0]["group_id"] == 1
    assert rows[1]["attention_level"] == "重点关注"
    assert rows[2]["attention_level"] == "建议查看"
    assert rows[3]["attention_level"] == "一般变化"
    assert body["kpis"]["changed_competitors_today"] == 14


def test_confirmed_multi_sku_strong_event_calibration(client, monkeypatch) -> None:
    _today(monkeypatch)
    with client[1]() as session:
        groups = [CompetitorGroup(id=i, name=f"G{i}", created_at=datetime(2026, 9, 1)) for i in (1, 2)]
        session.add_all(groups)
        session.flush()
        for group in groups:
            _competitor(session, 10 + group.id, group.id, "own")
        discount = _competitor(session, 21, 1, "competitor")
        sold_out = _competitor(session, 22, 2, "competitor")
        for index, sku in enumerate(("s1", "s2"), 1):
            _event(session, discount, "price_decrease", datetime(2026, 9, 20, index), entity=sku, delta_rate=-5)
            _event(session, sold_out, "sku_sold_out", datetime(2026, 9, 20, index), entity=sku)
        session.commit()

    response = client[0].get("/api/dashboard/group-attention")

    assert response.status_code == 200
    levels = {group["group_name"]: group["attention_level"] for group in response.json()["groups"]}
    assert levels == {"G1": "重点关注", "G2": "建议查看"}


def test_price_reversal_is_neutral_and_reasons_are_limited_to_three(
    client: tuple[TestClient, sessionmaker[Session]], monkeypatch,
) -> None:
    _today(monkeypatch)
    with client[1]() as session:
        group = CompetitorGroup(id=1, name="A19", created_at=datetime(2026, 9, 1))
        session.add(group)
        session.flush()
        _competitor(session, 1, group.id, "own")
        competitor = _competitor(session, 2, group.id, "competitor")
        _event(session, competitor, "price_decrease", datetime(2026, 9, 20, 1), entity="s1", delta_rate=-6)
        _event(session, competitor, "price_increase", datetime(2026, 9, 20, 2), entity="s1", delta_rate=6)
        _event(session, competitor, "sku_removed", datetime(2026, 9, 20, 3), entity="s2")
        _event(session, competitor, "title_changed", datetime(2026, 9, 20, 4))
        _event(session, competitor, "min_order_quantity_decrease", datetime(2026, 9, 20, 5))
        session.commit()

    row = client[0].get("/api/dashboard/group-attention").json()["groups"][0]

    assert len(row["reasons"]) == 3
    assert row["reasons"][0]["reason_type"] == "price_adjusted_multiple_times"
    assert "降价" not in row["reasons"][0]["display_text"]
    assert all(reason["current_state_safe"] for reason in row["reasons"])


def test_sold_out_then_restocked_and_offline_then_online_use_safe_reasons(
    client: tuple[TestClient, sessionmaker[Session]], monkeypatch,
) -> None:
    _today(monkeypatch)
    with client[1]() as session:
        group = CompetitorGroup(id=1, name="A19", created_at=datetime(2026, 9, 1))
        session.add(group)
        session.flush()
        _competitor(session, 1, group.id, "own")
        competitor = _competitor(session, 2, group.id, "competitor")
        _event(session, competitor, "sku_sold_out", datetime(2026, 9, 20, 1), entity="s1")
        _event(session, competitor, "sku_restocked", datetime(2026, 9, 20, 2), entity="s1")
        _event(session, competitor, "product_offline", datetime(2026, 9, 20, 3))
        _event(session, competitor, "product_online", datetime(2026, 9, 20, 4))
        session.commit()

    reasons = client[0].get("/api/dashboard/group-attention").json()["groups"][0]["reasons"]

    assert {reason["reason_type"] for reason in reasons} == {"sku_supply_changed", "lifecycle_changed"}
    assert all(reason["current_state_safe"] for reason in reasons)


def test_kpis_apply_own_product_eligibility_and_shanghai_half_open_day(
    client: tuple[TestClient, sessionmaker[Session]], monkeypatch,
) -> None:
    _today(monkeypatch)
    with client[1]() as session:
        eligible = CompetitorGroup(id=1, name="eligible", created_at=datetime(2026, 9, 1))
        no_own = CompetitorGroup(id=2, name="no own", created_at=datetime(2026, 9, 1))
        no_competitor = CompetitorGroup(id=3, name="no competitor", created_at=datetime(2026, 9, 1))
        idle = CompetitorGroup(id=4, name="idle", created_at=datetime(2026, 9, 1))
        session.add_all([eligible, no_own, no_competitor, idle])
        session.flush()
        _competitor(session, 1, eligible.id, "own")
        inside = _competitor(session, 2, eligible.id, "competitor")
        no_own_competitor = _competitor(session, 3, no_own.id, "competitor")
        _competitor(session, 4, no_competitor.id, "own")
        _competitor(session, 5, idle.id, "own")
        idle_competitor = _competitor(session, 6, idle.id, "competitor")
        _event(session, inside, "price_decrease", START_UTC)
        _event(session, inside, "price_decrease", END_UTC)
        _event(session, no_own_competitor, "price_decrease", START_UTC)
        _event(session, idle_competitor, "title_changed", START_UTC - __import__("datetime").timedelta(seconds=1))
        session.commit()

    body = client[0].get("/api/dashboard/group-attention").json()

    assert body["kpis"] == {
        "monitored_product_groups": 2,
        "changed_product_groups_today": 1,
        "changed_competitors_today": 1,
    }
    assert [row["group_id"] for row in body["groups"]] == [1]


def test_repeat_price_and_stock_events_deduplicate_sku_facts(
    client: tuple[TestClient, sessionmaker[Session]], monkeypatch,
) -> None:
    _today(monkeypatch)
    with client[1]() as session:
        group = CompetitorGroup(id=1, name="A19", created_at=datetime(2026, 9, 1))
        session.add(group)
        session.flush()
        _competitor(session, 1, group.id, "own")
        competitor = _competitor(session, 2, group.id, "competitor")
        for hour, sku in ((1, "s1"), (2, "s1"), (3, "s2")):
            _event(session, competitor, "price_decrease", datetime(2026, 9, 20, hour), entity=sku, delta_rate=-2)
        for hour in (4, 5, 6):
            _event(session, competitor, "stock_decrease", datetime(2026, 9, 20, hour), entity="s1")
        session.commit()

    reasons = client[0].get("/api/dashboard/group-attention").json()["groups"][0]["reasons"]
    price = next(reason for reason in reasons if reason["reason_type"] == "price_decrease")
    stock = next(reason for reason in reasons if reason["reason_type"] == "stock_changed")

    assert price["sku_count"] == 2
    assert "多个 SKU" in price["display_text"]
    assert stock["sku_count"] == 1
    assert stock["competitor_count"] == 1


def test_stock_coverage_does_not_combine_skus_from_different_snapshots(
    client: tuple[TestClient, sessionmaker[Session]], monkeypatch,
) -> None:
    _today(monkeypatch)
    with client[1]() as session:
        baseline = CompetitorGroup(id=1, name="baseline", created_at=datetime(2026, 9, 1))
        split = CompetitorGroup(id=2, name="split snapshots", created_at=datetime(2026, 9, 1))
        session.add_all([baseline, split])
        session.flush()
        baseline_competitor = _competitor(session, 1, baseline.id, "competitor")
        split_competitor = _competitor(session, 2, split.id, "competitor")
        _competitor(session, 11, baseline.id, "own")
        _competitor(session, 12, split.id, "own")

        def add_snapshot_events(competitor: Competitor, at: datetime, all_skus: list[str], changed: list[str]) -> None:
            snapshot = ProductSnapshot(
                competitor_id=competitor.id, captured_at=at, title=competitor.title or "",
                shop_name=competitor.shop_name or "", product_status="active", collection_source="html",
            )
            snapshot.skus = [SkuSnapshot(sku_id=sku, sku_name=sku, stock=10) for sku in all_skus]
            session.add(snapshot)
            session.flush()
            session.add_all([
                ChangeEvent(
                    competitor_id=competitor.id, snapshot_id=snapshot.id, change_type="stock_decrease",
                    entity_key=sku, old_value="10", new_value="9", detected_at=at,
                )
                for sku in changed
            ])

        add_snapshot_events(baseline_competitor, datetime(2026, 9, 20, 3), [f"base-{i}" for i in range(16)], [f"base-{i}" for i in range(4)])
        shared = [f"shared-{i}" for i in range(8)]
        add_snapshot_events(split_competitor, datetime(2026, 9, 20, 2), shared + ["a1", "a2"], ["a1", "a2"])
        add_snapshot_events(split_competitor, datetime(2026, 9, 20, 3), shared + ["b1", "b2"], ["b1", "b2"])
        session.commit()

    response = client[0].get("/api/dashboard/group-attention")

    assert response.status_code == 200
    assert [group["group_name"] for group in response.json()["groups"]] == ["baseline", "split snapshots"]
