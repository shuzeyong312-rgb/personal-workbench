"""Validate 1688 procurement-assistant sales fields without touching the app model."""

from __future__ import annotations

import json
import math
import re
import sqlite3
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "backend" / "data" / "personal_workbench.db"
PROFILE_DIR = ROOT / ".browser-profile"
API_NAME = "mtop.1688.pc.plugin.od.data.query"
FIELDS = (
    "last30DaysSales",
    "totalSales",
    "totalOrder",
    "saleQuantityList",
    "saleRangeList",
    "tradePriceList",
)
MISSING = object()
DATE_FORMATS = (
    (re.compile(r"^\d{8}$"), "%Y%m%d", "YYYYMMDD"),
    (re.compile(r"^\d{4}-\d{2}-\d{2}$"), "%Y-%m-%d", "YYYY-MM-DD"),
    (re.compile(r"^\d{4}/\d{2}/\d{2}$"), "%Y/%m/%d", "YYYY/MM/DD"),
)
LOGIN_MARKERS = ("login.1688.com", "/member/signin", "/member/login")
VERIFICATION_MARKERS = ("captcha", "verify", "punish", "secdev", "slide")


def walk(value: Any):
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
            return


def find_value(data: Any, key: str) -> Any:
    for item in walk(data):
        if key in item:
            return item[key]
    return MISSING


def raw_type(value: Any) -> str:
    if value is MISSING:
        return "missing"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


def normalize_non_negative_int(value: Any) -> tuple[int | None, str]:
    if isinstance(value, bool) or value is None or value is MISSING:
        return None, "uncertain"
    if isinstance(value, int):
        return (value, "safe") if value >= 0 else (None, "uncertain")
    if isinstance(value, float):
        if math.isfinite(value) and value >= 0 and value.is_integer():
            return int(value), "safe"
        return None, "uncertain"
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not re.fullmatch(r"\d+(?:\.0+)?", text):
            return None, "uncertain"
        try:
            decimal = Decimal(text)
        except InvalidOperation:
            return None, "uncertain"
        if decimal >= 0 and decimal == decimal.to_integral_value():
            return int(decimal), "safe"
    return None, "uncertain"


def numeric_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None or value is MISSING:
        return None
    if isinstance(value, (int, float, str)):
        try:
            result = Decimal(str(value).strip().replace(",", ""))
        except (InvalidOperation, ValueError):
            return None
        return result if result.is_finite() and result >= 0 else None
    return None


def normalize_scalar(value: Any) -> dict[str, Any]:
    normalized, status = normalize_non_negative_int(value)
    result = {
        "present": value is not MISSING,
        "raw_type": raw_type(value),
        "normalized": normalized,
        "normalization": status,
    }
    if value is MISSING or value is None or isinstance(value, (str, int, float, bool)):
        result["raw_value"] = None if value is MISSING else value
    return result


def parse_date(value: Any) -> tuple[date | None, str]:
    if not isinstance(value, str):
        return None, "unknown"
    for pattern, fmt, label in DATE_FORMATS:
        if pattern.fullmatch(value):
            try:
                return datetime.strptime(value, fmt).date(), label
            except ValueError:
                return None, "invalid"
    return None, "unknown"


def list_shape(value: Any) -> dict[str, Any]:
    if not isinstance(value, list):
        return {"type": raw_type(value), "count": None, "item_keys": []}
    item_keys = sorted({key for item in value if isinstance(item, dict) for key in item})
    dates = [item.get("date") for item in value if isinstance(item, dict) and "date" in item]
    date_formats = sorted({parse_date(item)[1] for item in dates})
    return {
        "type": "list",
        "count": len(value),
        "item_keys": item_keys,
        "date_count": len(dates),
        "date_formats": date_formats,
    }


def sale_quantity_observation(value: Any) -> dict[str, Any]:
    result = list_shape(value)
    if not isinstance(value, list):
        return result | {"value_keys": [], "quantity_key": None, "history_sum": None, "sum_status": "cannot_compare"}

    items = [item for item in value if isinstance(item, dict)]
    value_keys = sorted({key for item in items for key in item if key != "date"})
    dated: list[tuple[date, dict[str, Any]]] = []
    date_formats: set[str] = set()
    invalid_dates = 0
    for item in items:
        parsed, fmt = parse_date(item.get("date"))
        date_formats.add(fmt)
        if parsed is None:
            invalid_dates += 1
        else:
            dated.append((parsed, item))

    numeric_keys = [
        key for key in value_keys
        if all(numeric_decimal(item.get(key)) is not None for item in items)
    ]
    quantity_key = numeric_keys[0] if len(numeric_keys) == 1 else None
    quantities: list[Decimal] = []
    if quantity_key is not None and len(dated) == len(items):
        recent = sorted(dated, key=lambda item: item[0])[-30:]
        quantities = [numeric_decimal(item[quantity_key]) for _, item in recent]
    valid_quantity = all(item is not None for item in quantities)
    history_sum = int(sum(quantities)) if valid_quantity else None
    ordered_dates = [item[0] for item in dated]
    unique_dates = set(ordered_dates)
    gaps = 0
    if unique_dates:
        span = (max(unique_dates) - min(unique_dates)).days + 1
        gaps = span - len(unique_dates)
    today = date.today()
    result.update(
        {
            "value_keys": value_keys,
            "date_formats": sorted(date_formats),
            "date_count": len(ordered_dates),
            "unique_date_count": len(unique_dates),
            "date_order": (
                "ascending" if ordered_dates == sorted(ordered_dates)
                else "descending" if ordered_dates == sorted(ordered_dates, reverse=True)
                else "mixed"
            ),
            "date_range": [str(min(unique_dates)), str(max(unique_dates))] if unique_dates else [],
            "missing_date_count_in_span": gaps,
            "duplicate_date_count": len(ordered_dates) - len(unique_dates),
            "zero_quantity_count": sum(1 for quantity in quantities if quantity == 0) if valid_quantity else None,
            "future_date_count": sum(1 for day in unique_dates if day > today),
            "invalid_date_count": invalid_dates,
            "quantity_key": quantity_key,
            "history_sum": history_sum,
            "history_count": len(quantities) if valid_quantity else 0,
            "sum_status": "safe" if valid_quantity and quantity_key is not None else "cannot_compare",
        }
    )
    return result


def observation(data: Any) -> dict[str, Any]:
    values = {field: find_value(data, field) for field in FIELDS}
    fields = {
        field: (normalize_scalar(value) if field not in {"saleQuantityList", "saleRangeList", "tradePriceList"} else {
            "present": value is not MISSING,
            "raw_type": raw_type(value),
            "normalized": None,
        })
        for field, value in values.items()
    }
    sale_quantity = sale_quantity_observation(values["saleQuantityList"])
    fields["saleQuantityList"].update(sale_quantity)
    fields["saleRangeList"].update(list_shape(values["saleRangeList"]))
    fields["tradePriceList"].update(list_shape(values["tradePriceList"]))
    last30 = fields["last30DaysSales"]["normalized"]
    history_sum = sale_quantity.get("history_sum")
    if last30 is None or history_sum is None:
        comparison = "cannot compare"
    else:
        comparison = "equal" if last30 == history_sum else "different"
    return {
        "fields": fields,
        "sale_quantity_observation": sale_quantity,
        "last30_vs_history_sum": comparison,
    }


def active_competitors() -> list[dict[str, Any]]:
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT id, platform, offer_id, url FROM competitors "
            "WHERE is_active = 1 ORDER BY id LIMIT 5"
        ).fetchall()
    return [dict(row) for row in rows]


def classify_page(page: Any) -> str | None:
    url = str(getattr(page, "url", "")).casefold()
    try:
        title = str(page.title()).casefold()
    except Exception:
        title = ""
    if any(marker in url for marker in VERIFICATION_MARKERS) or title in {"captcha", "verification", "滑动验证", "安全验证", "访问验证", "验证码"}:
        return "verification required"
    if any(marker in url for marker in LOGIN_MARKERS) or title in {"登录", "账号登录", "用户登录", "1688登录", "login", "signin", "sign in", "1688 login"}:
        return "login required"
    return None


def extension_present() -> bool:
    extension_root = PROFILE_DIR / "Default" / "Extensions"
    return extension_root.exists() and any(path.is_dir() for path in extension_root.iterdir())


def validate_one(context: Any, competitor: dict[str, Any]) -> dict[str, Any]:
    page = context.new_page()
    payloads: list[Any] = []
    request_seen = False

    def capture(response: Any) -> None:
        nonlocal request_seen
        if API_NAME not in response.url:
            return
        request_seen = True
        try:
            payloads.append(response.json())
        except Exception:
            return

    page.on("response", capture)
    result: dict[str, Any] = {
        "competitor_id": competitor["id"],
        "offer_id": competitor["offer_id"],
        "url": competitor["url"],
        "captured": False,
        "failure_reason": None,
    }
    try:
        page.goto(competitor["url"], wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(10_000)
        page_state = classify_page(page)
        if not payloads:
            if page_state:
                result["failure_reason"] = page_state
            elif not extension_present():
                result["failure_reason"] = "extension missing"
            elif request_seen:
                result["failure_reason"] = "unknown"
            else:
                result["failure_reason"] = "request not triggered"
            return result
        result["captured"] = True
        result["response_count"] = len(payloads)
        result.update(observation(payloads[-1]))
        return result
    except (PlaywrightTimeoutError, TimeoutError):
        result["failure_reason"] = "unknown"
        result["failure_detail"] = "navigation timeout"
        return result
    except PlaywrightError as error:
        result["failure_reason"] = "unknown"
        result["failure_detail"] = error.__class__.__name__
        return result
    finally:
        page.close()


def main() -> None:
    competitors = active_competitors()
    if not competitors:
        print(json.dumps({"sample_count": 0, "results": []}, ensure_ascii=False, indent=2))
        return
    if not PROFILE_DIR.exists():
        results = [
            {
                "competitor_id": item["id"],
                "offer_id": item["offer_id"],
                "url": item["url"],
                "captured": False,
                "failure_reason": "extension missing",
            }
            for item in competitors
        ]
        print(json.dumps({"sample_count": len(results), "results": results}, ensure_ascii=False, indent=2))
        return

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            ignore_default_args=["--no-sandbox", "--disable-extensions"],
        )
        try:
            results = [validate_one(context, item) for item in competitors]
        finally:
            context.close()
    print(json.dumps({"sample_count": len(results), "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
