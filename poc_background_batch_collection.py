"""Validate headed window parking, manual verification resume, and two-page batches."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

from app.collection.collector_1688 import (  # noqa: E402
    CollectionTimeoutError,
    LoginRequiredError,
    PageUnavailableError,
    VerificationRequiredError,
    _LOGIN_TITLE_EXACT,
    _LOGIN_URL_MARKERS,
    _VERIFICATION_SELECTORS,
    _VERIFICATION_TITLE_EXACT,
    _VERIFICATION_URL_MARKERS,
)
from app.collection.parser_1688 import (  # noqa: E402
    CollectionParseError,
    OfferIdMismatchError,
    parse_1688_html,
)
from poc_headless_collection import (  # noqa: E402
    DB_PATH,
    NAVIGATION_TIMEOUT_MS,
    NETWORK_WAIT_MS,
    PROFILE_PATH,
    active_verified_competitors,
    error_reason,
    exception_view,
    html_shows_challenge,
    product_view,
    sales_view,
)
from poc_main_image_validation import (  # noqa: E402
    _collect_candidates,
    _eligible_dom_urls,
    _select_candidate,
)


WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 800
HIDDEN_COORDINATE = -32000
VERIFICATION_POLL_SECONDS = 1.5
DEFAULT_VERIFICATION_TIMEOUT_SECONDS = 120
DEFAULT_WINDOW_WAIT_SECONDS = 5


@dataclass
class BatchState:
    verification_timeout: float
    pause_event: asyncio.Event = field(default_factory=asyncio.Event)
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    resume_event: asyncio.Event = field(default_factory=asyncio.Event)
    verification_gate: asyncio.Lock = field(default_factory=asyncio.Lock)
    verification_active: bool = False
    verification_events: int = 0
    active_pages: int = 0
    max_active_pages: int = 0
    window_events: list[dict[str, Any]] = field(default_factory=list)


def _failure_result(
    competitor: dict[str, Any],
    *,
    reason: str,
    error: BaseException | None = None,
    page_number: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "competitor_id": competitor["id"],
        "expected_offer_id": str(competitor["offer_id"]),
        "status": "failed",
        "failure_reason": reason,
    }
    if page_number is not None:
        result["page_number"] = page_number
    if error is not None:
        result.update(exception_view(error))
    return result


async def _window_session(context: Any, page: Any) -> tuple[Any, Any, int, dict[str, Any]]:
    page_cdp = await context.new_cdp_session(page)
    browser = context.browser
    if browser is None:
        await page_cdp.detach()
        raise RuntimeError("persistent context has no browser")
    browser_cdp = await browser.new_browser_cdp_session()
    try:
        target = await page_cdp.send("Target.getTargetInfo")
        target_id = target["targetInfo"]["targetId"]
        window = await browser_cdp.send("Browser.getWindowForTarget", {"targetId": target_id})
        return page_cdp, browser_cdp, window["windowId"], window["bounds"]
    except Exception:
        await browser_cdp.detach()
        await page_cdp.detach()
        raise


async def _set_window_bounds(
    context: Any,
    page: Any,
    bounds: dict[str, Any],
) -> dict[str, Any]:
    page_cdp, browser_cdp, window_id, before = await _window_session(context, page)
    try:
        await browser_cdp.send(
            "Browser.setWindowBounds",
            {"windowId": window_id, "bounds": bounds},
        )
        after = await browser_cdp.send(
            "Browser.getWindowForTarget",
            {"targetId": (await page_cdp.send("Target.getTargetInfo"))["targetInfo"]["targetId"]},
        )
        return {
            "ok": True,
            "window_id": window_id,
            "requested_bounds": bounds,
            "before": before,
            "after": after["bounds"],
        }
    finally:
        await browser_cdp.detach()
        await page_cdp.detach()


async def hide_browser_window(context: Any, page: Any) -> dict[str, Any]:
    """Move the headed Chrome window outside the visible desktop without minimizing it."""
    return await _set_window_bounds(
        context,
        page,
        {
            "left": HIDDEN_COORDINATE,
            "top": HIDDEN_COORDINATE,
            "width": WINDOW_WIDTH,
            "height": WINDOW_HEIGHT,
            "windowState": "normal",
        },
    )


async def show_browser_window(context: Any, page: Any) -> dict[str, Any]:
    """Restore a normal centered-ish window and bring the verification page forward."""
    screen = await page.evaluate(
        """() => ({
            width: window.screen.availWidth || 1920,
            height: window.screen.availHeight || 1080
        })"""
    )
    width = min(WINDOW_WIDTH, max(800, int(screen["width"]) - 80))
    height = min(WINDOW_HEIGHT, max(600, int(screen["height"]) - 120))
    normalized = await _set_window_bounds(
        context,
        page,
        {"windowState": "normal"},
    )
    result = await _set_window_bounds(
        context,
        page,
        {
            "left": max(0, (int(screen["width"]) - width) // 2),
            "top": max(0, (int(screen["height"]) - height) // 2),
            "width": width,
            "height": height,
            "windowState": "normal",
        },
    )
    await page.bring_to_front()
    result["normalized_window"] = normalized
    result["brought_to_front"] = True
    return result


async def _async_main_image_view(html: str, page: Any) -> dict[str, Any]:
    try:
        context_value = await page.evaluate("() => window.context ?? null")
        candidates = _collect_candidates(html, context_value)
        dom_images = await page.evaluate(
            """() => Array.from(document.images).map((img) => {
                const rect = img.getBoundingClientRect();
                const style = getComputedStyle(img);
                const parent = img.parentElement;
                return {
                    src: img.getAttribute('src') || '',
                    currentSrc: img.currentSrc || '',
                    naturalWidth: img.naturalWidth || 0,
                    naturalHeight: img.naturalHeight || 0,
                    width: rect.width,
                    height: rect.height,
                    visible: style.display !== 'none' && style.visibility !== 'hidden'
                        && rect.width > 0 && rect.height > 0,
                    alt: img.getAttribute('alt') || '',
                    id: img.id || '',
                    className: typeof img.className === 'string' ? img.className : '',
                    parentClassName: parent && typeof parent.className === 'string'
                        ? parent.className : '',
                    parentId: parent ? parent.id || '' : ''
                };
            })"""
        )
        dom_urls = _eligible_dom_urls(dom_images if isinstance(dom_images, list) else [])
        selected = _select_candidate(candidates, dom_urls)
        if selected is None:
            return {"status": "not_found"}
        return {
            "status": "captured",
            "url": selected.canonical_url,
            "source_path": selected.path,
            "source_key": selected.source_key,
        }
    except Exception as error:
        return {"status": "observation_failed", **exception_view(error)}


async def _check_page_access_async(page: Any, status: int | None) -> None:
    page_url = page.url
    try:
        title = await page.title()
    except Exception:
        title = ""
    lowered_url = page_url.casefold()
    normalized_title = " ".join(title.casefold().split())
    if any(marker.casefold() in lowered_url for marker in _VERIFICATION_URL_MARKERS):
        raise VerificationRequiredError("1688 verification is required")
    if normalized_title in _VERIFICATION_TITLE_EXACT:
        raise VerificationRequiredError("1688 verification is required")
    for selector in _VERIFICATION_SELECTORS:
        try:
            locator = page.locator(selector)
            if await locator.count() and await locator.first.is_visible():
                raise VerificationRequiredError("1688 verification is required")
        except VerificationRequiredError:
            raise
        except Exception:
            continue
    if any(marker.casefold() in lowered_url for marker in _LOGIN_URL_MARKERS):
        raise LoginRequiredError("1688 login is required")
    if normalized_title in _LOGIN_TITLE_EXACT:
        raise LoginRequiredError("1688 login is required")
    if status is not None and status >= 400:
        raise PageUnavailableError("1688 page returned an unavailable status")
    hostname = (urlparse(page_url).hostname or "").casefold()
    if hostname and not hostname.endswith(".1688.com") and hostname != "1688.com":
        raise PageUnavailableError("1688 redirected to an unavailable page")


async def _parse_page(
    page: Any,
    competitor: dict[str, Any],
    status: int | None = None,
) -> tuple[Any, str, int | None]:
    html = await page.content()
    await _check_page_access_async(page, status)
    if html_shows_challenge(html):
        raise VerificationRequiredError("1688 verification page detected in HTML")
    product = parse_1688_html(html, str(competitor["offer_id"]))
    return product, html, status


async def _wait_for_restored_product(
    page: Any,
    competitor: dict[str, Any],
    state: BatchState,
) -> tuple[Any | None, str | None]:
    deadline = asyncio.get_running_loop().time() + state.verification_timeout
    while asyncio.get_running_loop().time() < deadline:
        if state.stop_event.is_set():
            return None, "verification_timeout"
        try:
            product, _, _ = await _parse_page(page, competitor)
            if product.offer_id == str(competitor["offer_id"]):
                return product, None
        except (
            VerificationRequiredError,
            LoginRequiredError,
            CollectionParseError,
            PlaywrightError,
            PlaywrightTimeoutError,
        ):
            pass
        await asyncio.sleep(VERIFICATION_POLL_SECONDS)
    return None, "verification_timeout"


async def _coordinate_verification(
    context: Any,
    page: Any,
    competitor: dict[str, Any],
    state: BatchState,
) -> tuple[Any | None, str | None]:
    async with state.verification_gate:
        if state.verification_active:
            owner = False
            resume_event = state.resume_event
        else:
            owner = True
            state.verification_active = True
            state.pause_event.set()
            state.resume_event.clear()
            resume_event = state.resume_event

    if not owner:
        try:
            await asyncio.wait_for(resume_event.wait(), state.verification_timeout)
        except asyncio.TimeoutError:
            return None, "verification_timeout"
        return None, "verification_required"

    try:
        try:
            window_result = await show_browser_window(context, page)
            state.window_events.append({"event": "show_for_verification", **window_result})
        except Exception as error:
            state.stop_event.set()
            state.window_events.append(
                {"event": "show_for_verification", "ok": False, **exception_view(error)}
            )
            return None, "window_management_failed"

        print("检测到 1688 人工验证，请在浏览器中完成验证。", flush=True)
        product, reason = await _wait_for_restored_product(page, competitor, state)
        if product is None:
            state.stop_event.set()
            print("人工验证等待超时，安全停止批次。", flush=True)
            return None, reason or "verification_timeout"

        print("人工验证完成，继续采集。", flush=True)
        try:
            window_result = await hide_browser_window(context, page)
            state.window_events.append({"event": "hide_after_verification", **window_result})
        except Exception as error:
            state.stop_event.set()
            state.window_events.append(
                {"event": "hide_after_verification", "ok": False, **exception_view(error)}
            )
            return None, "window_management_failed"
        return product, None
    finally:
        state.verification_active = False
        state.pause_event.clear()
        state.resume_event.set()


async def _wait_if_paused(state: BatchState) -> bool:
    while state.pause_event.is_set():
        if state.stop_event.is_set():
            return False
        try:
            await asyncio.wait_for(state.resume_event.wait(), 1.0)
        except asyncio.TimeoutError:
            continue
    return not state.stop_event.is_set()


async def collect_page(
    context: Any,
    page: Any,
    competitor: dict[str, Any],
    state: BatchState,
    page_number: int,
) -> dict[str, Any]:
    responses: list[Any] = []

    def capture(response: Any) -> None:
        if "mtop.1688.pc.plugin.od.data.query" in response.url:
            responses.append(response)

    page.on("response", capture)
    async with state.verification_gate:
        state.active_pages += 1
        state.max_active_pages = max(state.max_active_pages, state.active_pages)
    try:
        try:
            response = await page.goto(
                competitor["url"],
                wait_until="domcontentloaded",
                timeout=NAVIGATION_TIMEOUT_MS,
            )
            product, html, _ = await _parse_page(
                page,
                competitor,
                response.status if response is not None else None,
            )
            result: dict[str, Any] = {
                "competitor_id": competitor["id"],
                "expected_offer_id": str(competitor["offer_id"]),
                "page_number": page_number,
                "status": "success",
                "verification_detected": False,
                "response_status": response.status if response is not None else None,
                "product": product_view(product, str(competitor["offer_id"])),
            }
        except VerificationRequiredError:
            state.verification_events += 1
            product, reason = await _coordinate_verification(context, page, competitor, state)
            if product is None:
                return _failure_result(
                    competitor,
                    reason=reason or "verification_required",
                    page_number=page_number,
                )
            html = await page.content()
            result = {
                "competitor_id": competitor["id"],
                "expected_offer_id": str(competitor["offer_id"]),
                "page_number": page_number,
                "status": "success",
                "verification_detected": True,
                "product": product_view(product, str(competitor["offer_id"])),
            }
        except (PlaywrightTimeoutError, TimeoutError) as error:
            return _failure_result(competitor, reason="timeout", error=error, page_number=page_number)
        except PlaywrightError as error:
            return _failure_result(
                competitor,
                reason="page_unavailable",
                error=error,
                page_number=page_number,
            )
        except Exception as error:
            return _failure_result(
                competitor,
                reason=error_reason(error),
                error=error,
                page_number=page_number,
            )

        if not await _wait_if_paused(state):
            return _failure_result(
                competitor,
                reason="verification_required",
                page_number=page_number,
            )
        await page.wait_for_timeout(NETWORK_WAIT_MS)
        await _check_page_access_async(page, None)
        sales_payloads: list[Any] = []
        for response in responses:
            try:
                sales_payloads.append(await response.json())
            except Exception:
                continue
        result["sales"] = sales_view(sales_payloads, bool(responses))
        result["main_image"] = await _async_main_image_view(await page.content(), page)
        return result
    except VerificationRequiredError:
        state.verification_events += 1
        product, reason = await _coordinate_verification(context, page, competitor, state)
        if product is None:
            return _failure_result(
                competitor,
                reason=reason or "verification_required",
                page_number=page_number,
            )
        result["status"] = "success"
        result["verification_detected"] = True
        result["product"] = product_view(product, str(competitor["offer_id"]))
        result["sales"] = sales_view([], bool(responses))
        result["main_image"] = await _async_main_image_view(await page.content(), page)
        return result
    finally:
        page.remove_listener("response", capture)
        async with state.verification_gate:
            state.active_pages -= 1


async def window_sequence(
    context: Any,
    page: Any,
    state: BatchState,
    wait_seconds: float,
) -> dict[str, Any]:
    result: dict[str, Any] = {"hide_show_hide": False, "events": []}
    try:
        hidden = await hide_browser_window(context, page)
        result["events"].append({"event": "hide_initial", **hidden})
        await page.wait_for_timeout(int(wait_seconds * 1000))
        await page.evaluate("() => document.readyState")
        shown = await show_browser_window(context, page)
        result["events"].append({"event": "show_initial", **shown})
        hidden_again = await hide_browser_window(context, page)
        result["events"].append({"event": "hide_again", **hidden_again})
        result["hide_show_hide"] = all(event.get("ok") for event in result["events"])
    except Exception as error:
        result["events"].append({"event": "window_sequence_failed", "ok": False, **exception_view(error)})
    state.window_events.extend(result["events"])
    return result


async def _new_pages(context: Any, count: int) -> list[Any]:
    for old_page in list(context.pages):
        await old_page.close()
    return [await context.new_page() for _ in range(count)]


async def run_scenario(
    playwright: Any,
    name: str,
    competitors: list[dict[str, Any]],
    args: argparse.Namespace,
) -> dict[str, Any]:
    state = BatchState(args.verification_timeout)
    result: dict[str, Any] = {
        "scenario": name,
        "headless": False,
        "browser_launch_count": 0,
        "context_reused": False,
        "page_count": 1 if name == "serial" else 2,
        "results": [],
    }
    context = None
    try:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_PATH),
            channel="chrome",
            headless=False,
            ignore_default_args=["--no-sandbox"],
        )
        result["browser_launch_count"] = 1
        result["context_reused"] = True
        pages = await _new_pages(context, result["page_count"])
        result["window_sequence"] = await window_sequence(
            context, pages[0], state, args.window_wait
        )
        if name == "serial":
            for competitor in competitors:
                if not await _wait_if_paused(state):
                    break
                result["results"].append(
                    await collect_page(context, pages[0], competitor, state, 1)
                )
        else:
            async def worker(page_number: int, worker_competitors: list[dict[str, Any]]) -> None:
                for competitor in worker_competitors:
                    if not await _wait_if_paused(state):
                        return
                    item = await collect_page(
                        context, pages[page_number - 1], competitor, state, page_number
                    )
                    result["results"].append(item)

            await asyncio.gather(
                worker(1, competitors[::2]),
                worker(2, competitors[1::2]),
            )
        result["verification_events"] = state.verification_events
        result["max_active_pages"] = state.max_active_pages
        result["window_events"] = state.window_events
        result["stop_requested"] = state.stop_event.is_set()
    except Exception as error:
        result.update({"scenario_error": True, **exception_view(error)})
    finally:
        if context is not None:
            try:
                await context.close()
                result["context_closed"] = True
            except Exception as error:
                result["context_closed"] = False
                result["context_close_error"] = exception_view(error)
    return result


async def reopen_probe(playwright: Any) -> bool:
    context = None
    try:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_PATH),
            channel="chrome",
            headless=False,
            ignore_default_args=["--no-sandbox"],
        )
        return True
    except Exception:
        return False
    finally:
        if context is not None:
            await context.close()


def compare_scenarios(
    serial: dict[str, Any], concurrent: dict[str, Any]
) -> list[dict[str, Any]]:
    serial_by_id = {item["competitor_id"]: item for item in serial["results"]}
    comparisons: list[dict[str, Any]] = []
    for item in concurrent["results"]:
        other = serial_by_id.get(item["competitor_id"])
        if other is None:
            continue
        comparisons.append(
            {
                "competitor_id": item["competitor_id"],
                "serial_status": other.get("status"),
                "concurrent_status": item.get("status"),
                "core_fields_equal": (
                    other.get("product") == item.get("product")
                    if other.get("status") == item.get("status") == "success"
                    else False
                ),
                "serial_sales_status": other.get("sales", {}).get("status"),
                "concurrent_sales_status": item.get("sales", {}).get("status"),
                "serial_main_image_status": other.get("main_image", {}).get("status"),
                "concurrent_main_image_status": item.get("main_image", {}).get("status"),
            }
        )
    return comparisons


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=("both", "serial", "concurrent"), default="both")
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument(
        "--verification-timeout",
        type=float,
        default=DEFAULT_VERIFICATION_TIMEOUT_SECONDS,
    )
    parser.add_argument("--window-wait", type=float, default=DEFAULT_WINDOW_WAIT_SECONDS)
    return parser.parse_args()


async def async_main(args: argparse.Namespace) -> None:
    competitors = active_verified_competitors(args.samples)
    report: dict[str, Any] = {
        "poc": "1688-background-batch-validation",
        "database": str(DB_PATH),
        "profile": str(PROFILE_PATH),
        "sample_count": len(competitors),
        "samples": competitors,
        "window": {
            "hidden_coordinate": [HIDDEN_COORDINATE, HIDDEN_COORDINATE],
            "normal_size": [WINDOW_WIDTH, WINDOW_HEIGHT],
            "cdp": ["Browser.getWindowForTarget", "Browser.setWindowBounds"],
        },
        "scenarios": {},
    }
    async with async_playwright() as playwright:
        scenarios = ("serial", "concurrent") if args.scenario == "both" else (args.scenario,)
        for scenario in scenarios:
            report["scenarios"][scenario] = await run_scenario(
                playwright, scenario, competitors, args
            )
        if "serial" in report["scenarios"] and "concurrent" in report["scenarios"]:
            report["comparisons"] = compare_scenarios(
                report["scenarios"]["serial"], report["scenarios"]["concurrent"]
            )
        report["profile_reopen_probe"] = await reopen_probe(playwright)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main() -> None:
    args = parse_args()
    if not 1 <= args.samples <= 5:
        raise SystemExit("--samples must be between 1 and 5")
    if args.verification_timeout <= 0 or args.window_wait < 0:
        raise SystemExit("timeouts must be positive")
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
