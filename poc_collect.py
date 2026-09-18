import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from playwright.sync_api import sync_playwright


URL = "https://detail.1688.com/offer/1081895898799.html"


def embedded_value(html: str, key: str):
    marker = f'"{key}"'
    start = html.find(marker)
    if start < 0:
        return None
    colon = html.find(":", start + len(marker))
    if colon < 0:
        return None
    try:
        return json.JSONDecoder().raw_decode(html[colon + 1 :].lstrip())[0]
    except json.JSONDecodeError:
        return None


def embedded_values(html: str, key: str):
    values = []
    offset = 0
    marker = f'"{key}"'
    while (start := html.find(marker, offset)) >= 0:
        value = embedded_value(html[start:], key)
        if value is not None:
            values.append(value)
        offset = start + len(marker)
    return values


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)
    elif isinstance(value, str) and value[:1] in "[{":
        try:
            yield from walk(json.loads(value))
        except json.JSONDecodeError:
            pass


def first_value(data, keys):
    for item in walk(data):
        for key in keys:
            value = item.get(key)
            if isinstance(value, (str, int, float)) and str(value).strip():
                return str(value)
    return None


def find_map(data, key):
    for item in walk(data):
        value = item.get(key)
        if isinstance(value, dict):
            return value
    return None


def values_for_keys(data, keys):
    return {
        key: list(dict.fromkeys(
            str(item[key]) for item in walk(data)
            if isinstance(item.get(key), (str, int, float)) and str(item[key]).strip()
        ))[:10]
        for key in keys
    }


def sku_name(sku):
    spec_attrs = sku.get("specAttrs")
    if isinstance(spec_attrs, str) and spec_attrs.strip():
        return spec_attrs
    values = []
    for item in walk(sku):
        for key in ("valueDisplayName", "valueName", "name", "value"):
            value = item.get(key)
            if isinstance(value, str) and value.strip() and value not in values:
                values.append(value)
    return " / ".join(values) if values else "unavailable"


def format_price(value):
    if value is None:
        return "unavailable"
    try:
        return f"{Decimal(value):.2f}"
    except (InvalidOperation, ValueError):
        return str(value)


def main() -> None:
    profile_dir = Path(__file__).parent / ".browser-profile"
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            channel="chrome",
            headless=False,
            ignore_default_args=["--no-sandbox"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        response = page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        html = response.text() if response else page.content()
        context_json = page.evaluate("() => JSON.stringify(window.context ?? null)")
        context.close()

    context_data = json.loads(context_json) if context_json else None
    sku_info_map = find_map(context_data, "skuInfoMap") or embedded_value(html, "skuInfoMap")
    if not isinstance(sku_info_map, dict):
        raise RuntimeError("未在 HTML 内嵌数据中解析到 skuInfoMap")

    offer_id = first_value(context_data, ("offerId",)) or URL.rsplit("/", 1)[-1].removesuffix(".html")
    title = first_value(context_data, ("subject", "title", "offerTitle"))
    shop = first_value(context_data, ("companyName", "shopName", "sellerName"))
    price = first_value(context_data, ("priceText", "priceDisplay", "priceRange"))
    sku_price_scale = next(iter(embedded_values(html, "skuPriceScale")), None)
    skus = [sku for sku in sku_info_map.values() if isinstance(sku, dict)]
    if not all((title, shop, price)) or any(
        sku_name(sku) == "unavailable" or "skuPriceScale" not in sku for sku in skus
    ):
        debug = {
            "skuInfoMap_item_keys": sorted({key for sku in sku_info_map.values() if isinstance(sku, dict) for key in sku}),
            "title_candidates": values_for_keys(context_data, ("subject", "title", "offerTitle")),
            "shop_candidates": values_for_keys(context_data, ("companyName", "shopName", "sellerName")),
            "price_candidates": values_for_keys(context_data, ("priceText", "priceDisplay", "priceRange", "priceAmount")),
            "skuPriceScale_in_html": embedded_values(html, "skuPriceScale"),
            "skuId_containing_map_keys": [
                sorted(item) for item in walk(context_data) if "skuId" in item
            ][:10],
        }
        (Path(__file__).parent / "poc_collect_debug.json").write_text(
            json.dumps(debug, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    print(f"offerId：{offer_id}")
    print(f"商品：{title or 'unavailable'}")
    print(f"店铺：{shop or 'unavailable'}")
    print(f"价格：{format_price(price)}")
    print(f"skuPriceScale（商品级原始字段）：{sku_price_scale or 'unavailable'}")
    print("SKU：")
    for map_key, sku in sku_info_map.items():
        if not isinstance(sku, dict):
            continue
        print(
            f"- {sku_name(sku)} | skuId={sku.get('skuId', map_key)}"
            f" | canBookCount={sku.get('canBookCount', 'unavailable')}"
            f" | skuPriceScale={sku.get('skuPriceScale', 'unavailable')}"
        )


if __name__ == "__main__":
    main()
