import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterator

from app.collection.types import ProductData, SkuData


class CollectionParseError(ValueError):
    """The page does not contain the required product facts."""


class OfferIdMismatchError(CollectionParseError):
    """The page belongs to a different offer than the requested one."""


_INTEGER = re.compile(r"^\d+$")
_PRICE = re.compile(
    r"^\s*[¥￥]?\s*(\d+(?:\.\d+)?)\s*(?:[-~至到]\s*[¥￥]?\s*(\d+(?:\.\d+)?))?\s*$"
)
_SKU_PRICE = re.compile(r"^\s*[¥￥]?\s*(\d+(?:\.\d+)?)\s*$")


def _embedded_values(html: str, key: str) -> list[Any]:
    values: list[Any] = []
    marker = f'"{key}"'
    offset = 0
    decoder = json.JSONDecoder(parse_float=Decimal)
    while (start := html.find(marker, offset)) >= 0:
        colon = html.find(":", start + len(marker))
        if colon >= 0:
            try:
                values.append(decoder.raw_decode(html[colon + 1 :].lstrip())[0])
            except json.JSONDecodeError:
                pass
        offset = start + len(marker)
    return values


def _walk(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)
    elif isinstance(value, str) and value[:1] in "[{":
        try:
            yield from _walk(json.loads(value, parse_float=Decimal))
        except json.JSONDecodeError:
            return


def _offer_id(values: list[Any]) -> str | None:
    for value in values:
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, int):
            return str(value)
        if isinstance(value, str) and _INTEGER.fullmatch(value.strip()):
            return value.strip()
    return None


def _text_value(values: list[Any]) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _first_dict(values: list[Any]) -> dict[str, Any] | None:
    for value in values:
        if isinstance(value, dict):
            return value
    return None


def _parse_price(value: Any) -> tuple[Decimal, Decimal] | None:
    if not isinstance(value, (str, int, Decimal)) or isinstance(value, bool):
        return None
    match = _PRICE.fullmatch(str(value))
    if not match:
        return None
    try:
        minimum = Decimal(match.group(1))
        maximum = Decimal(match.group(2) or match.group(1))
    except InvalidOperation:
        return None
    return minimum, maximum


def _product_price(html: str) -> tuple[Decimal, Decimal] | None:
    for key in ("priceText", "priceDisplay", "priceRange", "skuPriceScale"):
        for value in _embedded_values(html, key):
            price = _parse_price(value)
            if price is not None:
                return price
    return None


def _sku_name(sku: dict[str, Any]) -> str:
    spec_attrs = sku.get("specAttrs")
    if isinstance(spec_attrs, str) and spec_attrs.strip():
        return spec_attrs.strip()
    values: list[str] = []
    for item in _walk(spec_attrs):
        for key in ("valueDisplayName", "valueName", "name", "value"):
            value = item.get(key)
            if isinstance(value, str) and value.strip() and value not in values:
                values.append(value.strip())
    return " / ".join(values) or "unavailable"


def _stock(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and _INTEGER.fullmatch(value.strip()):
        return int(value)
    return None


def _parse_sku_price(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        return None
    match = _SKU_PRICE.fullmatch(str(value))
    if not match:
        return None
    try:
        price = Decimal(match.group(1))
    except InvalidOperation:
        return None
    return price if price.is_finite() and price >= 0 else None


def _min_order_quantity(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 1 else None
    if isinstance(value, str) and _INTEGER.fullmatch(value.strip()):
        try:
            quantity = int(value)
        except (ValueError, OverflowError):
            return None
        return quantity if quantity >= 1 else None
    return None


def _sku_id(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def parse_1688_html(html: str, expected_offer_id: str | None = None) -> ProductData:
    """Parse only HTML/embedded JSON into the internal collection contract."""
    offer_id = _offer_id(_embedded_values(html, "offerId"))
    if not offer_id:
        raise CollectionParseError("missing or invalid offer_id")
    if expected_offer_id is not None and offer_id != str(expected_offer_id):
        raise OfferIdMismatchError(
            f"offer_id mismatch: expected {expected_offer_id}, got {offer_id}"
        )

    title = _text_value(_embedded_values(html, "subject")) or _text_value(
        _embedded_values(html, "title")
    ) or _text_value(_embedded_values(html, "offerTitle"))
    shop_name = _text_value(_embedded_values(html, "companyName")) or _text_value(
        _embedded_values(html, "shopName")
    ) or _text_value(_embedded_values(html, "sellerName"))

    if not title or not shop_name:
        raise CollectionParseError("missing required product fields")

    sku_info_map = _first_dict(_embedded_values(html, "skuInfoMap")) or {}
    skus = []
    min_order_values: list[int | None] = []
    for sku in sku_info_map.values():
        if not isinstance(sku, dict):
            continue
        sku_id = _sku_id(sku.get("skuId"))
        if sku_id is None:
            raise CollectionParseError("missing or invalid sku_id")
        min_order_values.append(_min_order_quantity(sku.get("priceAmount")))
        skus.append(
            SkuData(
                sku_id=sku_id,
                sku_name=_sku_name(sku),
                stock=_stock(sku.get("canBookCount")),
                price=_parse_sku_price(sku.get("discountPrice")),
            )
        )
    price = _product_price(html)
    min_order_quantity = None
    if skus and all(value is not None for value in min_order_values):
        values = {value for value in min_order_values if value is not None}
        if len(values) == 1:
            min_order_quantity = values.pop()
    return ProductData(
        offer_id=offer_id,
        title=title,
        shop_name=shop_name,
        main_image_url=None,
        price_min=price[0] if price else None,
        price_max=price[1] if price else None,
        product_status="unknown",
        collection_source="html",
        captured_at=datetime.now(timezone.utc),
        skus=skus,
        min_order_quantity=min_order_quantity,
    )
