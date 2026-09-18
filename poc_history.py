import json
from pathlib import Path

from playwright.sync_api import sync_playwright


URL = "https://detail.1688.com/offer/1081895898799.html"
API_NAME = "mtop.1688.pc.plugin.od.data.query"
FIELDS = (
    "last30DaysSales",
    "totalSales",
    "totalOrder",
    "saleQuantityList",
    "saleRangeList",
    "tradePriceList",
)


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


def find_value(data, key):
    for item in walk(data):
        if key in item:
            return item[key]
    return None


def print_list(label, values):
    print(f"{label}：")
    if not isinstance(values, list):
        print("unavailable")
        return
    for value in values:
        if isinstance(value, dict) and isinstance(value.get("date"), str):
            date = value["date"]
            display_date = f"{date[:4]}-{date[4:6]}-{date[6:]}" if len(date) == 8 else date
            fields = " | ".join(f"{key}={item}" for key, item in value.items() if key != "date")
            print(f"{display_date} -> {fields}")
        else:
            print(json.dumps(value, ensure_ascii=False))


def main() -> None:
    profile_dir = Path(__file__).parent / ".browser-profile"
    payloads = []

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            channel="chrome",
            headless=False,
            ignore_default_args=["--no-sandbox", "--disable-extensions"],
        )
        page = context.pages[0] if context.pages else context.new_page()

        def capture(response):
            if API_NAME not in response.url:
                return
            try:
                payloads.append(response.json())
            except Exception:
                pass

        page.on("response", capture)
        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_timeout(10000)
        context.close()

    if not payloads:
        print(f"未捕获接口：{API_NAME}")
        if not (profile_dir / "Default" / "Extensions").exists():
            print("原因：当前 .browser-profile 未安装浏览器扩展，商品页不会自动触发该插件接口。")
        else:
            print("原因待确认：商品页在当前 Chrome 会话中未自动触发该请求。")
        return

    data = payloads[-1]
    values = {field: find_value(data, field) for field in FIELDS}
    missing = [field for field, value in values.items() if value is None]
    if missing:
        (Path(__file__).parent / "poc_history_debug.json").write_text(
            json.dumps({"response_top_level_keys": sorted(data), "missing_fields": missing}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print("已捕获接口：" + API_NAME)
    print(f"近30天销量：{values['last30DaysSales'] if values['last30DaysSales'] is not None else 'unavailable'}")
    print(f"累计销量：{values['totalSales'] if values['totalSales'] is not None else 'unavailable'}")
    print(f"累计订单：{values['totalOrder'] if values['totalOrder'] is not None else 'unavailable'}")
    print_list("销量历史", values["saleQuantityList"])
    print_list("saleRangeList", values["saleRangeList"])
    print_list("价格历史", values["tradePriceList"])


if __name__ == "__main__":
    main()
