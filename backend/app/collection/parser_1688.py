import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterator
from urllib.parse import urlparse

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


def _json_object(value: object) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value, parse_float=Decimal)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def normalize_main_image_url(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value:
        return None
    if value.startswith("//"):
        value = f"https:{value}"
    try:
        parsed = urlparse(value)
        hostname = parsed.hostname
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not hostname or not parsed.path:
        return None
    return parsed._replace(fragment="").geturl()


def _gallery_image_url(html: str, field: str) -> str | None:
    for gallery in _embedded_values(html, "gallery"):
        if not isinstance(gallery, dict):
            continue
        fields = gallery.get("fields")
        if not isinstance(fields, dict):
            continue
        images = fields.get(field)
        if not isinstance(images, list) or not images:
            continue
        image_url = normalize_main_image_url(images[0])
        if image_url is not None:
            return image_url
    return None


def _data_json_image_url(html: str) -> str | None:
    for root in _embedded_values(html, "Root"):
        root_object = _json_object(root)
        if root_object is None:
            continue
        fields = root_object.get("fields")
        if not isinstance(fields, dict):
            continue
        data_json = _json_object(fields.get("dataJson"))
        if data_json is None:
            continue
        images = data_json.get("images")
        if not isinstance(images, list) or not images:
            continue
        first_image = images[0]
        if not isinstance(first_image, dict):
            continue
        image_url = normalize_main_image_url(first_image.get("fullPathImageURI"))
        if image_url is not None:
            return image_url
    return None


def _main_image_url(html: str) -> str | None:
    return (
        _gallery_image_url(html, "offerImgList")
        or _gallery_image_url(html, "mainImage")
        or _data_json_image_url(html)
    )


def _gallery_image_urls(html: str) -> list[str]:
    image_urls: list[str] = []
    for gallery in _embedded_values(html, "gallery"):
        if not isinstance(gallery, dict):
            continue
        fields = gallery.get("fields")
        if not isinstance(fields, dict):
            continue
        images = fields.get("offerImgList")
        if not isinstance(images, list):
            continue
        for raw_image in images:
            image_url = normalize_main_image_url(raw_image)
            if image_url is not None and image_url not in image_urls:
                image_urls.append(image_url)
    return image_urls


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
    main_image_url = _main_image_url(html)
    image_urls: list[str] = []
    if main_image_url is not None:
        image_urls.append(main_image_url)
    for image_url in _gallery_image_urls(html):
        if image_url not in image_urls:
            image_urls.append(image_url)
    return ProductData(
        offer_id=offer_id,
        title=title,
        shop_name=shop_name,
        main_image_url=main_image_url,
        image_urls=image_urls,
        price_min=price[0] if price else None,
        price_max=price[1] if price else None,
        product_status="unknown",
        collection_source="html",
        captured_at=datetime.now(timezone.utc),
        skus=skus,
        min_order_quantity=min_order_quantity,
    )
