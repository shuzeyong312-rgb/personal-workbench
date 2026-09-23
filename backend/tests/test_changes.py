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

    assert changes == [ChangeDraft("price_increase", None, "40.00", "45.00", Decimal("5"), Decimal("12.5"))]


def test_uniform_price_decrease() -> None:
    changes = detect_changes(
        product_snapshot(price_min=Decimal("45"), price_max=Decimal("45")),
        product_data(price_min=Decimal("40"), price_max=Decimal("40")),
    )

    assert changes == [ChangeDraft("price_decrease", None, "45.00", "40.00", Decimal("-5"), Decimal("-11.11111111111111111111111111"))]


def test_price_range_change_has_no_single_delta() -> None:
    assert detect_changes(
        product_snapshot(price_min=Decimal("40"), price_max=Decimal("50")),
        product_data(price_min=Decimal("35"), price_max=Decimal("45")),
    ) == [ChangeDraft("price_decrease", None, "40.00~50.00", "35.00~45.00")]


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

    assert changes == [
        ChangeDraft("stock_increase", "sku-1", "10", "20", Decimal("10"), Decimal("100"))
    ]


def test_stock_change_from_zero_is_reported() -> None:
    changes = detect_changes(
        product_snapshot(skus=[sku_snapshot("sku-1", "红色", stock=0)]),
        product_data(skus=[sku_data("sku-1", "红色", stock=10)]),
    )

    assert changes == [
        ChangeDraft("sku_restocked", "sku-1", "0", "10", Decimal("10"), None)
    ]


def test_stock_change_to_zero_is_reported() -> None:
    changes = detect_changes(
        product_snapshot(skus=[sku_snapshot("sku-1", "红色", stock=10)]),
        product_data(skus=[sku_data("sku-1", "红色", stock=0)]),
    )

    assert changes == [
        ChangeDraft("sku_sold_out", "sku-1", "10", "0", Decimal("-10"), Decimal("-100"))
    ]


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
        ChangeDraft("price_increase", None, "40.00", "45.00", Decimal("5"), Decimal("12.5")),
        ChangeDraft("stock_increase", "sku-1", "10", "20", Decimal("10"), Decimal("100")),
        ChangeDraft("sku_added", "sku-2", None, "蓝色"),
        ChangeDraft("sku_removed", "sku-3", "绿色", None),
        ChangeDraft("title_changed", None, "A", "B"),
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


@pytest.mark.parametrize(
    ("previous_url", "current_url", "expected"),
    [
        ("https://img.example.com/a.jpg", "https://img.example.com/a.jpg", []),
        (
            "https://img.example.com/a.jpg",
            "https://img.example.com/b.jpg",
            [ChangeDraft("main_image_changed", None, "https://img.example.com/a.jpg", "https://img.example.com/b.jpg")],
        ),
        (None, "https://img.example.com/a.jpg", []),
        ("https://img.example.com/a.jpg", None, []),
        (None, None, []),
    ],
)
def test_main_image_change_matrix(
    previous_url: str | None,
    current_url: str | None,
    expected: list[ChangeDraft],
) -> None:
    assert detect_changes(
        product_snapshot(main_image_url=previous_url),
        product_data(main_image_url=current_url),
    ) == expected


def test_main_image_change_chain_only_reports_adjacent_differences() -> None:
    baseline = product_snapshot(main_image_url="https://img.example.com/a.jpg")
    changed = product_data(main_image_url="https://img.example.com/b.jpg")
    unchanged = product_data(main_image_url="https://img.example.com/b.jpg")
    changed_again = product_data(main_image_url="https://img.example.com/c.jpg")

    assert detect_changes(baseline, changed) == [
        ChangeDraft(
            "main_image_changed",
            None,
            "https://img.example.com/a.jpg",
            "https://img.example.com/b.jpg",
        )
    ]
    assert detect_changes(
        product_snapshot(main_image_url=changed.main_image_url), unchanged
    ) == []
    assert detect_changes(
        product_snapshot(main_image_url=unchanged.main_image_url), changed_again
    ) == [
        ChangeDraft(
            "main_image_changed",
            None,
            "https://img.example.com/b.jpg",
            "https://img.example.com/c.jpg",
        )
    ]


def test_image_urls_change_without_main_image_change_is_ignored() -> None:
    previous = product_snapshot(
        main_image_url="https://img.example.com/a.jpg",
        image_urls=["https://img.example.com/a.jpg", "https://img.example.com/old-detail.jpg"],
    )
    current = product_data(
        main_image_url="https://img.example.com/a.jpg",
        image_urls=["https://img.example.com/a.jpg", "https://img.example.com/new-detail.jpg"],
    )

    assert detect_changes(previous, current) == []


def test_product_status_change_is_ignored() -> None:
    assert detect_changes(
        product_snapshot(product_status="unknown"),
        product_data(product_status="offline"),
    ) == []


def test_sku_price_change_is_reported_with_sku_entity() -> None:
    assert detect_changes(
        product_snapshot(skus=[sku_snapshot("sku-1", "红色", price=Decimal("10"))]),
        product_data(skus=[sku_data("sku-1", "红色", price=Decimal("20"))]),
    ) == [ChangeDraft("price_increase", "sku-1", "10.00", "20.00", Decimal("10"), Decimal("100"))]


@pytest.mark.parametrize(
    ("old_price", "new_price"),
    [(None, Decimal("20")), (Decimal("20"), None)],
)
def test_sku_price_with_unknown_side_is_ignored(
    old_price: Decimal | None,
    new_price: Decimal | None,
) -> None:
    assert detect_changes(
        product_snapshot(skus=[sku_snapshot("sku-1", "红色", price=old_price)]),
        product_data(skus=[sku_data("sku-1", "红色", price=new_price)]),
    ) == []


def test_added_and_removed_skus_do_not_emit_price_or_stock_events() -> None:
    changes = detect_changes(
        product_snapshot(skus=[sku_snapshot("old", "旧", stock=10, price=Decimal("10"))]),
        product_data(skus=[sku_data("new", "新", stock=20, price=Decimal("20"))]),
    )

    assert changes == [
        ChangeDraft("sku_added", "new", None, "新"),
        ChangeDraft("sku_removed", "old", "旧", None),
    ]


def test_min_order_quantity_changes_are_directional_and_numeric() -> None:
    assert detect_changes(
        product_snapshot(min_order_quantity=5),
        product_data(min_order_quantity=1),
    ) == [ChangeDraft("min_order_quantity_decrease", None, "5", "1", Decimal("-4"), Decimal("-80"))]
    assert detect_changes(
        product_snapshot(min_order_quantity=1),
        product_data(min_order_quantity=5),
    ) == [ChangeDraft("min_order_quantity_increase", None, "1", "5", Decimal("4"), Decimal("400"))]


@pytest.mark.parametrize(
    ("old_quantity", "new_quantity"),
    [(None, 1), (1, None), (None, None), (0, 1), (1, 0)],
)
def test_invalid_or_unknown_min_order_quantity_is_ignored(
    old_quantity: int | None,
    new_quantity: int | None,
) -> None:
    assert detect_changes(
        product_snapshot(min_order_quantity=old_quantity),
        product_data(min_order_quantity=new_quantity),
    ) == []


def test_stock_events_are_exclusive_for_sold_out_and_restocked() -> None:
    sold_out = detect_changes(
        product_snapshot(skus=[sku_snapshot("sku-1", "红色", stock=100)]),
        product_data(skus=[sku_data("sku-1", "红色", stock=0)]),
    )
    restocked = detect_changes(
        product_snapshot(skus=[sku_snapshot("sku-1", "红色", stock=0)]),
        product_data(skus=[sku_data("sku-1", "红色", stock=100)]),
    )
    assert [change.change_type for change in sold_out] == ["sku_sold_out"]
    assert [change.change_type for change in restocked] == ["sku_restocked"]


def test_multiple_v2_events_have_stable_domain_and_sku_order() -> None:
    changes = detect_changes(
        product_snapshot(
            price_min=Decimal("40"),
            price_max=Decimal("40"),
            min_order_quantity=5,
            title="旧标题",
            skus=[
                sku_snapshot("sku-2", "二", stock=0, price=Decimal("22")),
                sku_snapshot("sku-1", "一", stock=10, price=Decimal("11")),
            ],
        ),
        product_data(
            price_min=Decimal("35"),
            price_max=Decimal("35"),
            min_order_quantity=1,
            title="新标题",
            skus=[
                sku_data("sku-2", "二", stock=20, price=Decimal("20")),
                sku_data("sku-1", "一", stock=0, price=Decimal("12")),
            ],
        ),
    )

    assert [(change.change_type, change.entity_key) for change in changes] == [
        ("price_decrease", None),
        ("price_increase", "sku-1"),
        ("price_decrease", "sku-2"),
        ("sku_sold_out", "sku-1"),
        ("sku_restocked", "sku-2"),
        ("min_order_quantity_decrease", None),
        ("title_changed", None),
    ]
