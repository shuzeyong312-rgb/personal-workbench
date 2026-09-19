from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.collection.types import ProductData, SkuData
from app.changes import ChangeDraft, detect_changes
from app.models import ProductSnapshot, SkuSnapshot


def product_snapshot(**overrides: object) -> ProductSnapshot:
    values: dict[str, object] = {
        "title": "商品标题",
        "shop_name": "店铺",
        "price_min": Decimal("40"),
        "price_max": Decimal("40"),
        "product_status": "unknown",
        "main_image_url": None,
        "skus": [],
    }
    values.update(overrides)
    return ProductSnapshot(**values)


def product_data(**overrides: object) -> ProductData:
    values: dict[str, object] = {
        "offer_id": "offer-1",
        "title": "商品标题",
        "shop_name": "店铺",
        "main_image_url": None,
        "price_min": Decimal("40"),
        "price_max": Decimal("40"),
        "product_status": "unknown",
        "collection_source": "html",
        "captured_at": datetime(2026, 9, 19, tzinfo=timezone.utc),
        "skus": [],
    }
    values.update(overrides)
    return ProductData(**values)


def sku_snapshot(
    sku_id: str,
    sku_name: str,
    stock: int | None = None,
    price: Decimal | None = None,
) -> SkuSnapshot:
    return SkuSnapshot(sku_id=sku_id, sku_name=sku_name, stock=stock, price=price)


def sku_data(
    sku_id: str,
    sku_name: str,
    stock: int | None = None,
    price: Decimal | None = None,
) -> SkuData:
    return SkuData(sku_id=sku_id, sku_name=sku_name, stock=stock, price=price)


def test_first_collection_establishes_baseline_without_changes() -> None:
    assert detect_changes(None, product_data()) == []


def test_identical_product_data_has_no_changes() -> None:
    assert detect_changes(product_snapshot(), product_data()) == []


def test_uniform_price_increase() -> None:
    changes = detect_changes(
        product_snapshot(price_min=Decimal("40"), price_max=Decimal("40")),
        product_data(price_min=Decimal("45"), price_max=Decimal("45")),
    )

    assert changes == [ChangeDraft("price_increase", None, "40.00", "45.00")]


def test_uniform_price_decrease() -> None:
    changes = detect_changes(
        product_snapshot(price_min=Decimal("45"), price_max=Decimal("45")),
        product_data(price_min=Decimal("40"), price_max=Decimal("40")),
    )

    assert changes == [ChangeDraft("price_decrease", None, "45.00", "40.00")]


@pytest.mark.parametrize(
    ("old_min", "old_max", "new_min", "new_max"),
    [
        (None, Decimal("40"), Decimal("45"), Decimal("45")),
        (Decimal("40"), None, Decimal("45"), Decimal("45")),
        (Decimal("40"), Decimal("40"), None, Decimal("45")),
        (Decimal("40"), Decimal("40"), Decimal("45"), None),
        (Decimal("40"), Decimal("50"), Decimal("40"), Decimal("55")),
        (Decimal("40"), Decimal("50"), Decimal("42"), Decimal("48")),
    ],
)
def test_incomplete_or_mixed_direction_price_has_no_event(
    old_min: Decimal | None,
    old_max: Decimal | None,
    new_min: Decimal | None,
    new_max: Decimal | None,
) -> None:
    assert detect_changes(
        product_snapshot(price_min=old_min, price_max=old_max),
        product_data(price_min=new_min, price_max=new_max),
    ) == []


def test_new_sku_produces_sku_added() -> None:
    changes = detect_changes(
        product_snapshot(skus=[sku_snapshot("sku-1", "红色")]),
        product_data(skus=[sku_data("sku-1", "红色"), sku_data("sku-2", "蓝色")]),
    )

    assert changes == [ChangeDraft("sku_added", "sku-2", None, "蓝色")]


def test_missing_sku_produces_sku_removed() -> None:
    changes = detect_changes(
        product_snapshot(skus=[sku_snapshot("sku-1", "红色"), sku_snapshot("sku-2", "蓝色")]),
        product_data(skus=[sku_data("sku-1", "红色")]),
    )

    assert changes == [ChangeDraft("sku_removed", "sku-2", "蓝色", None)]


def test_same_sku_id_with_new_name_is_not_added_or_removed() -> None:
    changes = detect_changes(
        product_snapshot(skus=[sku_snapshot("sku-1", "红色")]),
        product_data(skus=[sku_data("sku-1", "深红")]),
    )

    assert changes == []


def test_stock_change_is_reported_for_same_sku_id() -> None:
    changes = detect_changes(
        product_snapshot(skus=[sku_snapshot("sku-1", "红色", stock=10)]),
        product_data(skus=[sku_data("sku-1", "红色", stock=20)]),
    )

    assert changes == [ChangeDraft("stock_changed", "sku-1", "10", "20")]


def test_stock_change_from_zero_is_reported() -> None:
    changes = detect_changes(
        product_snapshot(skus=[sku_snapshot("sku-1", "红色", stock=0)]),
        product_data(skus=[sku_data("sku-1", "红色", stock=10)]),
    )

    assert changes == [ChangeDraft("stock_changed", "sku-1", "0", "10")]


def test_stock_change_to_zero_is_reported() -> None:
    changes = detect_changes(
        product_snapshot(skus=[sku_snapshot("sku-1", "红色", stock=10)]),
        product_data(skus=[sku_data("sku-1", "红色", stock=0)]),
    )

    assert changes == [ChangeDraft("stock_changed", "sku-1", "10", "0")]


@pytest.mark.parametrize(
    ("old_stock", "new_stock"),
    [(None, 10), (10, None), (None, None)],
)
def test_missing_stock_does_not_produce_event(
    old_stock: int | None,
    new_stock: int | None,
) -> None:
    assert detect_changes(
        product_snapshot(skus=[sku_snapshot("sku-1", "红色", stock=old_stock)]),
        product_data(skus=[sku_data("sku-1", "红色", stock=new_stock)]),
    ) == []


def test_title_change_is_reported() -> None:
    changes = detect_changes(
        product_snapshot(title="A"),
        product_data(title="B"),
    )

    assert changes == [ChangeDraft("title_changed", None, "A", "B")]


def test_equal_titles_do_not_produce_event() -> None:
    assert detect_changes(product_snapshot(title="A"), product_data(title="A")) == []


def test_multiple_changes_use_the_fixed_order() -> None:
    changes = detect_changes(
        product_snapshot(
            title="A",
            price_min=Decimal("40"),
            price_max=Decimal("40"),
            skus=[
                sku_snapshot("sku-1", "红色", stock=10),
                sku_snapshot("sku-3", "绿色", stock=5),
            ],
        ),
        product_data(
            title="B",
            price_min=Decimal("45"),
            price_max=Decimal("45"),
            skus=[
                sku_data("sku-1", "红色", stock=20),
                sku_data("sku-2", "蓝色", stock=3),
            ],
        ),
    )

    assert changes == [
        ChangeDraft("price_increase", None, "40.00", "45.00"),
        ChangeDraft("title_changed", None, "A", "B"),
        ChangeDraft("sku_added", "sku-2", None, "蓝色"),
        ChangeDraft("sku_removed", "sku-3", "绿色", None),
        ChangeDraft("stock_changed", "sku-1", "10", "20"),
    ]


def test_multiple_sku_events_are_sorted_by_sku_id() -> None:
    changes = detect_changes(
        product_snapshot(
            skus=[
                sku_snapshot("sku-3", "旧三"),
                sku_snapshot("sku-1", "旧一"),
            ]
        ),
        product_data(
            skus=[
                sku_data("sku-4", "新四"),
                sku_data("sku-2", "新二"),
            ]
        ),
    )

    assert [(change.change_type, change.entity_key) for change in changes] == [
        ("sku_added", "sku-2"),
        ("sku_added", "sku-4"),
        ("sku_removed", "sku-1"),
        ("sku_removed", "sku-3"),
    ]


def test_main_image_change_is_ignored() -> None:
    assert detect_changes(
        product_snapshot(main_image_url="old-image"),
        product_data(main_image_url="new-image"),
    ) == []


def test_product_status_change_is_ignored() -> None:
    assert detect_changes(
        product_snapshot(product_status="unknown"),
        product_data(product_status="offline"),
    ) == []


def test_sku_price_change_is_ignored() -> None:
    assert detect_changes(
        product_snapshot(skus=[sku_snapshot("sku-1", "红色", price=Decimal("10"))]),
        product_data(skus=[sku_data("sku-1", "红色", price=Decimal("20"))]),
    ) == []
