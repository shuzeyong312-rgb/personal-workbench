import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.collection.parser_1688 import (
    CollectionParseError,
    OfferIdMismatchError,
    _min_order_quantity,
    _parse_sku_price,
    parse_1688_html,
)


FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def embedded_page(payload: dict) -> str:
    return (
        '<script type="application/json">'
        + json.dumps(payload, ensure_ascii=False)
        + "</script>"
    )


def test_parses_verified_product_and_sku_fields() -> None:
    result = parse_1688_html(fixture("normal_product.html"), "1081895898799")

    assert result.offer_id == "1081895898799"
    assert result.title == "脱敏暖手宝"
    assert result.shop_name == "脱敏店铺"
    assert result.price_min == Decimal("40.00")
    assert result.price_max == Decimal("40.00")
    assert isinstance(result.price_min, Decimal)
    assert result.product_status == "unknown"
    assert result.collection_source == "html"
    assert isinstance(result.captured_at, datetime)
    assert [(sku.sku_id, sku.sku_name, sku.stock) for sku in result.skus] == [
        ("6300265722150", "颜色:粉色", 1000),
        ("6300265722149", "颜色:米白色", 990),
    ]
    assert all(sku.price is None for sku in result.skus)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("38.00", Decimal("38.00")),
        (79, Decimal("79")),
        ("¥38.00", Decimal("38.00")),
        ("￥38.00", Decimal("38.00")),
        (None, None),
        (True, None),
        ("invalid", None),
        ("79.00-89.00", None),
        ([], None),
    ],
)
def test_parse_sku_price_is_strict_and_never_uses_product_price(
    value: object, expected: Decimal | None
) -> None:
    assert _parse_sku_price(value) == expected

    result = parse_1688_html(
        embedded_page(
            {
                "offerId": "123",
                "subject": "标题",
                "shopName": "店铺",
                "priceText": "79.00",
                "skuInfoMap": {
                    "map-key": {"skuId": "sku-1", "price": "88.00"}
                },
            }
        )
    )
    assert result.skus[0].price is None


def test_sku_discount_prices_stay_on_their_skus_and_offer_quantity_is_common() -> None:
    result = parse_1688_html(
        embedded_page(
            {
                "offerId": "123",
                "subject": "标题",
                "shopName": "店铺",
                "skuInfoMap": {
                    "first": {
                        "skuId": "sku-79",
                        "specAttrs": "普通",
                        "discountPrice": 79,
                        "priceAmount": 1,
                    },
                    "second": {
                        "skuId": "sku-89",
                        "specAttrs": "加量",
                        "discountPrice": 89,
                        "priceAmount": 1,
                    },
                },
            }
        )
    )

    assert [(sku.sku_id, sku.price) for sku in result.skus] == [
        ("sku-79", Decimal("79")),
        ("sku-89", Decimal("89")),
    ]
    assert result.min_order_quantity == 1
    assert not hasattr(result.skus[0], "min_order_quantity")


@pytest.mark.parametrize(
    ("price_amounts", "expected"),
    [
        ([1, 1], 1),
        (["2", "2"], 2),
        ([1, None], None),
        ([1, "invalid"], None),
        ([1, 2], None),
        ([], None),
        ([True], None),
        ([0], None),
        ([-1], None),
    ],
)
def test_product_min_order_quantity_requires_all_sku_values_to_match(
    price_amounts: list[object], expected: int | None
) -> None:
    result = parse_1688_html(
        embedded_page(
            {
                "offerId": "123",
                "subject": "标题",
                "shopName": "店铺",
                "skuInfoMap": {
                    str(index): {
                        "skuId": f"sku-{index}",
                        "priceAmount": value,
                    }
                    for index, value in enumerate(price_amounts)
                },
            }
        )
    )
    assert result.min_order_quantity == expected
    assert all(not hasattr(sku, "min_order_quantity") for sku in result.skus)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1, 1),
        ("2", 2),
        (0, None),
        (-1, None),
        (True, None),
        ("1.5", None),
        (None, None),
        ("invalid", None),
        ({}, None),
    ],
)
def test_min_order_quantity_accepts_only_positive_integers(
    value: object, expected: int | None
) -> None:
    assert _min_order_quantity(value) == expected


def test_overlong_price_amount_keeps_product_parse_successful() -> None:
    result = parse_1688_html(
        embedded_page(
            {
                "offerId": "123",
                "subject": "标题",
                "shopName": "店铺",
                "skuInfoMap": {
                    "sku": {
                        "skuId": "sku-1",
                        "priceAmount": "9" * 5000,
                    }
                },
            }
        )
    )

    assert result.min_order_quantity is None
    assert [sku.sku_id for sku in result.skus] == ["sku-1"]


def test_missing_optional_values_are_none() -> None:
    result = parse_1688_html(fixture("minimal_product.html"))

    assert result.main_image_url is None
    assert result.price_min is None
    assert result.price_max is None
    assert result.skus[0].stock is None
    assert result.skus[0].price is None
    assert result.min_order_quantity is None


def test_expected_offer_id_mismatch_is_stable_error() -> None:
    with pytest.raises(OfferIdMismatchError, match="offer_id mismatch"):
        parse_1688_html(fixture("normal_product.html"), "other-offer")


def test_missing_required_field_is_parse_error() -> None:
    with pytest.raises(CollectionParseError, match="missing required product fields"):
        parse_1688_html(fixture("malformed_product.html"))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("offerId", True),
        ("subject", True),
        ("shopName", 123),
        ("subject", "   "),
    ],
)
def test_invalid_required_field_types_are_parse_errors(field: str, value: object) -> None:
    payload = {"offerId": "123", "subject": "标题", "shopName": "店铺"}
    payload[field] = value

    with pytest.raises(CollectionParseError):
        parse_1688_html(embedded_page(payload))


def test_integer_offer_id_is_normalized_to_string() -> None:
    result = parse_1688_html(
        embedded_page({"offerId": 123, "subject": "标题", "shopName": "店铺"})
    )

    assert result.offer_id == "123"


def test_offer_id_mismatch_precedes_missing_product_fields() -> None:
    with pytest.raises(OfferIdMismatchError, match="offer_id mismatch"):
        parse_1688_html(
            embedded_page({"offerId": "123", "subject": "   "}),
            expected_offer_id="456",
        )


@pytest.mark.parametrize("sku_id", [None, "", True])
def test_invalid_sku_id_is_parse_error(sku_id: object) -> None:
    payload = {
        "offerId": "123",
        "subject": "标题",
        "shopName": "店铺",
        "skuInfoMap": {"map-key": {"skuId": sku_id, "specAttrs": "规格:默认"}},
    }

    with pytest.raises(CollectionParseError, match="missing or invalid sku_id"):
        parse_1688_html(embedded_page(payload))


def test_integer_sku_id_is_normalized_to_string() -> None:
    result = parse_1688_html(
        embedded_page(
            {
                "offerId": "123",
                "subject": "标题",
                "shopName": "店铺",
                "skuInfoMap": {
                    "map-key": {"skuId": 456, "specAttrs": "规格:默认"}
                },
            }
        )
    )

    assert result.skus[0].sku_id == "456"


def test_parser_has_no_browser_or_database_dependency() -> None:
    result = parse_1688_html(fixture("normal_product.html"))
    assert result.skus
