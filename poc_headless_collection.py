"""Validate headed/headless 1688 collection without changing the formal collector."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

from app.collection.collector_1688 import (  # noqa: E402
    CollectionTimeoutError,
    LoginRequiredError,
    PageUnavailableError,
    VerificationRequiredError,
    _check_page_access,
)
from app.collection.parser_1688 import (  # noqa: E402
    CollectionParseError,
    OfferIdMismatchError,
    parse_1688_html,
)
from poc_main_image_validation import (  # noqa: E402
    _collect_candidates,
    _context_value,
    _dom_images,
    _eligible_dom_urls,
    _select_candidate,
)
from poc_sales_validation import API_NAME, observation  # noqa: E402


DB_PATH = ROOT / "backend" / "data" / "personal_workbench.db"
PROFILE_PATH = ROOT / ".browser-profile"
NAVIGATION_TIMEOUT_MS = 30_000
NETWORK_WAIT_MS = 10_000
MAX_SAMPLES = 5


def active_verified_competitors(limit: int) -> list[dict[str, Any]]:
    connection = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT c.id, c.offer_id, c.url, c.title, c.shop_name,
                   (SELECT COUNT(*) FROM collection_runs r
                    WHERE r.competitor_id = c.id AND r.status = 'success') AS successful_runs
            FROM competitors c
            WHERE c.is_active = 1
              AND EXISTS (
                  SELECT 1 FROM collection_runs r
                  WHERE r.competitor_id = c.id AND r.status = 'success'
              )
            ORDER BY c.id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]


def product_view(product: Any, expected_offer_id: str) -> dict[str, Any]:
    return {
        "expected_offer_id": str(expected_offer_id),
        "actual_offer_id": product.offer_id,
        "title": product.title,
        "shop_name": product.shop_name,
        "price_min": str(product.price_min) if product.price_min is not None else None,
        "price_max": str(product.price_max) if product.price_max is not None else None,
        "sku_count": len(product.skus),
        "skus": [
            {"skuId": sku.sku_id, "sku_name": sku.sku_name, "stock": sku.stock}
            for sku in product.skus
        ],
    }


def error_reason(error: BaseException) -> str:
    if isinstance(error, LoginRequiredError):
        return "login_required"
    if isinstance(error, VerificationRequiredError):
        return "verification_required"
    if isinstance(error, PageUnavailableError):
        return "page_unavailable"
    if isinstance(error, CollectionTimeoutError) or isinstance(
        error, (PlaywrightTimeoutError, TimeoutError)
    ):
        return "timeout"
    if isinstance(error, OfferIdMismatchError):
        return "offer_id_mismatch"
    if isinstance(error, CollectionParseError):
        return "parse_failed"
    return "unknown"


def html_shows_challenge(html: str) -> bool:
    if '"offerId"' in html:
        return False
    lowered = html.casefold()
    return any(marker in lowered for marker in ("captcha", "verify", "punish", "secdev", "slide"))


def exception_view(error: BaseException) -> dict[str, str]:
    return {
        "exception_type": type(error).__name__,
        "exception_message": " ".join(str(error).split())[:500],
    }


def sales_view(payloads: list[Any], request_seen: bool) -> dict[str, Any]:
    if not payloads:
        return {
            "status": "response_seen_non_json" if request_seen else "network data missing",
            "fields_present": [],
        }
    observed = observation(payloads[-1])
    return {
        "status": "captured",
        "fields_present": sorted(
            key for key, value in observed["fields"].items() if value.get("present")
        ),
        "fields": observed["fields"],
        "last30_vs_history_sum": observed["last30_vs_history_sum"],
    }


def main_image_view(html: str, page: Any) -> dict[str, Any]:
    try:
        context_value = _context_value(page)
        candidates = _collect_candidates(html, context_value)
        dom_urls = _eligible_dom_urls(_dom_images(page))
        selected = _select_candidate(candidates, dom_urls)
        if selected is None:
            return {"status": "not_found"}
        return {
            "status": "captured",
            "url": selected.canonical_url,
            "source_path": selected.path,
            "source_key": selected.source_key,
        }
    except Exception as error:  # optional research observation must not hide core collection result
        return {"status": "observation_failed", **exception_view(error)}


def collect_one(context: Any, competitor: dict[str, Any], round_number: int) -> dict[str, Any]:
    page = context.new_page()
    payloads: list[Any] = []
    request_seen = False
    result: dict[str, Any] = {
        "round": round_number,
        "competitor_id": competitor["id"],
        "offer_id": competitor["offer_id"],
        "status": "failed",
        "failure_reason": None,
        "network_api": API_NAME,
    }

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
    try:
        try:
            response = page.goto(
                competitor["url"],
                wait_until="domcontentloaded",
                timeout=NAVIGATION_TIMEOUT_MS,
            )
        except (PlaywrightTimeoutError, TimeoutError) as error:
            raise CollectionTimeoutError("1688 page navigation timed out") from error
        except PlaywrightError as error:
            raise PageUnavailableError("1688 page navigation failed") from error

        try:
            html = page.content()
        except (PlaywrightTimeoutError, TimeoutError) as error:
            raise CollectionTimeoutError("1688 page content timed out") from error
        except PlaywrightError as error:
            raise PageUnavailableError("1688 page content was unavailable") from error

        status = response.status if response is not None else None
        page_title = page.title()
        lowered_html = html.casefold()
        result.update(
            {
                "response_status": status,
                "page_url": page.url,
                "page_title": page_title,
                "page_title_unicode_escape": page_title.encode("unicode_escape").decode("ascii"),
                "html_length": len(html),
                "html_offer_id_marker_count": html.count('"offerId"'),
                "html_challenge_markers": {
                    marker: lowered_html.count(marker)
                    for marker in ("captcha", "verify", "punish", "secdev", "slide", "验证", "安全")
                    if marker in lowered_html
                },
            }
        )
        _check_page_access(page, status)
        if html_shows_challenge(html):
            raise VerificationRequiredError("1688 verification page detected in HTML")
        product = parse_1688_html(html, str(competitor["offer_id"]))
        result.update(
            {
                "status": "success",
                "html_offer_id_match": product.offer_id == str(competitor["offer_id"]),
                "product": product_view(product, str(competitor["offer_id"])),
            }
        )

        page.wait_for_timeout(NETWORK_WAIT_MS)
        _check_page_access(page, None)
        result["sales"] = sales_view(payloads, request_seen)
        result["main_image"] = main_image_view(page.content(), page)
        return result
    except Exception as error:
        result.update({"failure_reason": error_reason(error), **exception_view(error)})
        result["sales"] = sales_view(payloads, request_seen)
        return result
    finally:
        page.close()


def launch_failure(error: BaseException) -> str:
    message = str(error).casefold()
    if "already in use" in message or "user data directory" in message:
        return "profile_lock"
    return "browser_launch_failed"


def run_mode(mode: str, competitors: list[dict[str, Any]], rounds: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "mode": mode,
        "headless": mode == "headless",
        "rounds_requested": rounds,
        "browser_launch_count": 0,
        "browser_context_reused": False,
        "results": [],
    }
    if not PROFILE_PATH.is_dir():
        result.update({"launch_failure_reason": "profile_missing", "profile_path": str(PROFILE_PATH)})
        return result

    with sync_playwright() as playwright:
        try:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_PATH),
                channel="chrome",
                headless=mode == "headless",
                ignore_default_args=["--no-sandbox"],
            )
        except Exception as error:
            result.update(
                {
                    "launch_failure_reason": launch_failure(error),
                    **exception_view(error),
                }
            )
            return result

        result.update({"browser_launch_count": 1, "browser_context_reused": True})
        try:
            for round_number in range(1, rounds + 1):
                for competitor in competitors:
                    result["results"].append(collect_one(context, competitor, round_number))
        finally:
            context.close()
    return result


CORE_KEYS = (
    "actual_offer_id",
    "title",
    "shop_name",
    "price_min",
    "price_max",
    "sku_count",
    "skus",
)


def core_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return all(left.get(key) == right.get(key) for key in CORE_KEYS)


def summarize_mode(mode_result: dict[str, Any], sample_count: int) -> dict[str, Any]:
    results = mode_result["results"]
    success_count = sum(item.get("status") == "success" for item in results)
    network_count = sum(item.get("sales", {}).get("status") == "captured" for item in results)
    reasons = Counter(
        item.get("failure_reason") or item.get("sales", {}).get("status")
        for item in results
        if item.get("status") != "success" or item.get("sales", {}).get("status") != "captured"
    )
    attempts = sample_count * mode_result["rounds_requested"]
    return {
        "attempts": attempts,
        "collection_successes": success_count,
        "collection_success_rate": f"{success_count}/{attempts}",
        "network_captures": network_count,
        "network_capture_rate": f"{network_count}/{attempts}",
        "failure_or_missing_reasons": dict(reasons),
        "browser_launch_count": mode_result["browser_launch_count"],
        "browser_context_reused": mode_result["browser_context_reused"],
    }


def compare_modes(
    headed: dict[str, Any], headless: dict[str, Any]
) -> list[dict[str, Any]]:
    headed_by_key = {
        (item["round"], item["competitor_id"]): item for item in headed["results"]
    }
    comparisons: list[dict[str, Any]] = []
    for item in headless["results"]:
        other = headed_by_key.get((item["round"], item["competitor_id"]))
        if other is None:
            continue
        comparison = {
            "round": item["round"],
            "competitor_id": item["competitor_id"],
            "headed_status": other.get("status"),
            "headless_status": item.get("status"),
            "core_fields_equal": bool(
                other.get("status") == item.get("status") == "success"
                and core_equal(other["product"], item["product"])
            ),
            "headed_network_status": other.get("sales", {}).get("status"),
            "headless_network_status": item.get("sales", {}).get("status"),
            "network_fields_equal": other.get("sales", {}).get("fields_present")
            == item.get("sales", {}).get("fields_present"),
            "main_image_equal": (
                other.get("main_image", {}).get("url")
                == item.get("main_image", {}).get("url")
                if other.get("main_image", {}).get("url")
                and item.get("main_image", {}).get("url")
                else None
            ),
        }
        comparisons.append(comparison)
    return comparisons


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("both", "headed", "headless"), default="both")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--samples", type=int, default=MAX_SAMPLES)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.rounds < 1 or not 1 <= args.samples <= MAX_SAMPLES:
        raise SystemExit("--rounds must be positive and --samples must be between 1 and 5")

    competitors = active_verified_competitors(args.samples)
    report: dict[str, Any] = {
        "poc": "1688-headless-collection-validation",
        "profile": str(PROFILE_PATH),
        "database": str(DB_PATH),
        "sample_count": len(competitors),
        "sample_selection": "active competitors with at least one successful headed collection run",
        "samples": competitors,
        "requested_rounds": args.rounds,
        "modes": {},
    }
    modes = ("headed", "headless") if args.mode == "both" else (args.mode,)
    for mode in modes:
        mode_result = run_mode(mode, competitors, args.rounds)
        mode_result["summary"] = summarize_mode(mode_result, len(competitors))
        report["modes"][mode] = mode_result

    if "headed" in report["modes"] and "headless" in report["modes"]:
        report["comparisons"] = compare_modes(report["modes"]["headed"], report["modes"]["headless"])
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
