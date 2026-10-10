from pathlib import Path
import re
from urllib.parse import urlparse
from datetime import datetime, timezone

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from app.collection.parser_1688 import OfferIdMismatchError, parse_1688_html, parse_1688_offer_id
from app.collection.types import CollectionPageResult, OperatingMetricData, ProductData


class CollectorError(RuntimeError):
    """Base class for stable Playwright collection errors."""


class LoginRequiredError(CollectorError):
    """The persistent 1688 session is no longer logged in."""


class VerificationRequiredError(CollectorError):
    """1688 requires a verification or risk-control step."""


class OfflineProductDetected(CollectorError):
    """1688 returned a page with the confirmed offline-product signal."""


class PageUnavailableError(CollectorError):
    """The target page could not be accessed."""


class CollectionTimeoutError(CollectorError):
    """Navigation or page loading exceeded the collection timeout."""


_NAVIGATION_TIMEOUT_MS = 30_000
_LOGIN_URL_MARKERS = ("login.1688.com", "/member/signin", "/member/login")
_VERIFICATION_URL_MARKERS = ("captcha", "verify", "punish", "secdev", "slide")
_LOGIN_TITLE_EXACT = frozenset(
    {
    "登录",
    "账号登录",
    "用户登录",
    "1688登录",
    "login",
    "signin",
    "sign in",
    "1688 login",
    }
)
_VERIFICATION_TITLE_EXACT = frozenset(
    {
    "captcha",
    "verification",
    "滑动验证",
    "安全验证",
    "访问验证",
    "验证码",
    }
)
_VERIFICATION_SELECTORS = ("#nc_1_wrapper",)
_BAXIA_PUNISH_SELECTOR = "#baxia-punish"
_BAXIA_CAPTCHA_TIPS_SELECTOR = "#baxia-punish .captcha-tips"
_BAXIA_VERIFICATION_TEXTS = (
    "请拖动下方滑块完成验证",
    "通过验证以确保正常访问",
)
_VERIFICATION_RECHECK_DELAY_MS = 300
_OFFLINE_SELECTOR = "h3.mod-detail-offline-title"
_OFFLINE_TEXT = "商品已下架"
_ASSISTANT_HEADER = "1688\u5b98\u65b9\u91c7\u8d2d\u52a9\u624b"
_ASSISTANT_REGION_CLASS = "goods-operation-panel-media"
_METRIC_LABELS = {
    "listing_time": "\u4e0a\u67b6\u65f6\u95f4",
    "monthly_deal": "\u6708\u6210\u4ea4",
    "monthly_dropship": "\u6708\u4ee3\u9500",
    "annual_units": "\u5e74\u6210\u4ea4\u4ef6\u6570",
    "annual_orders": "\u5e74\u6210\u4ea4\u7b14\u6570",
    "review_count": "\u8bc4\u8bba\u6570",
    "positive_rate": "\u597d\u8bc4\u7387",
    "pickup_rate": "\u63fd\u6536\u7387",
}
_METRIC_PLACEHOLDERS = {"-", "—", "–", "--", "\u6682\u65e0", "\u672a\u663e\u793a"}
_METRIC_LOADING = ("\u52a0\u8f7d\u4e2d", "\u6b63\u5728\u52a0\u8f7d", "\u6570\u636e\u52a0\u8f7d\u4e2d", "loading", "\u8bfb\u53d6\u4e2d", "\u83b7\u53d6\u4e2d")
_METRIC_SOURCE = "1688_official_procurement_assistant_top"


def _assistant_region(page: object) -> tuple[object | None, str | None]:
    try:
        headings = [item for item in page.get_by_text(_ASSISTANT_HEADER, exact=True).all() if item.is_visible()]
        if len(headings) != 1:
            return None, "\u5b98\u65b9\u91c7\u8d2d\u52a9\u624b\u6807\u9898\u4e0d\u5b58\u5728\u6216\u4e0d\u552f\u4e00"
        candidates = headings[0].evaluate(
            """el => {
              const found = [];
              let node = el;
              for (let depth = 0; node && node !== document.body && depth < 12; depth++, node = node.parentElement) {
                const style = getComputedStyle(node), rect = node.getBoundingClientRect();
                const visible = style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                if (visible && node.classList.contains('goods-operation-panel-media'))
                  found.push({depth, text: node.innerText || ''});
              }
              return found;
            }"""
        )
        candidates = [item for item in candidates if "\u5206\u9500\u4ee3\u53d1" not in item["text"]]
        if len(candidates) != 1 or _ASSISTANT_HEADER not in candidates[0]["text"]:
            return None, "\u65e0\u6cd5\u552f\u4e00\u786e\u8ba4\u5b98\u65b9\u52a9\u624b\u9876\u90e8\u533a\u57df"
        region = headings[0]
        for _ in range(int(candidates[0]["depth"])):
            region = region.locator("xpath=..")
        return region, None
    except Exception:
        return None, "\u8bfb\u53d6\u5b98\u65b9\u52a9\u624b\u9876\u90e8\u533a\u57df\u5931\u8d25"


def _assistant_metrics(page: object, offer_id: str) -> list[OperatingMetricData]:
    observed_at = datetime.now(timezone.utc)
    region, region_error = _assistant_region(page)
    read_error = None
    text = ""
    if region is not None:
        try:
            text = region.inner_text()
        except Exception:
            read_error = "\u8bfb\u53d6\u5b98\u65b9\u52a9\u624b\u9876\u90e8\u533a\u57df\u5931\u8d25"
    text = re.sub(r"(?<!\S)(" + "|".join(map(re.escape, _METRIC_LABELS.values())) + r")(?=\s|[:：]|$)", r"\n\1", text)
    lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    labels = set(_METRIC_LABELS.values())
    results = []
    for key, label in _METRIC_LABELS.items():
        raw_value = None
        matches = []
        for index, line in enumerate(lines):
            if line == label:
                matches.append(lines[index + 1] if index + 1 < len(lines) and lines[index + 1] not in labels else None)
            elif line.startswith(label + " ") or line.startswith(label + ":") or line.startswith(label + "："):
                matches.append(re.sub(r"^" + re.escape(label) + r"\s*[:：]?\s*", "", line).strip() or None)
        if read_error:
            status, reason = "read_failed", read_error
        elif region_error:
            status, reason = "source_unavailable", region_error
        elif len(matches) > 1:
            status, reason = "read_failed", "\u5b98\u65b9\u52a9\u624b\u533a\u57df\u5b58\u5728\u91cd\u590d\u5b57\u6bb5\u6807\u7b7e"
        elif not matches:
            loading = any(marker.casefold() in text.casefold() for marker in _METRIC_LOADING)
            status, reason = ("loading", "\u5b98\u65b9\u52a9\u624b\u5b57\u6bb5\u4ecd\u5728\u52a0\u8f7d") if loading else ("source_unavailable", "\u5b98\u52a9\u624b\u672a\u663e\u793a\u8be5\u5b57\u6bb5")
        elif matches:
            raw_value = matches[0]
            if raw_value is None:
                status, reason = "read_failed", "\u5b57\u6bb5\u6807\u7b7e\u53ef\u89c1\u4f46\u6ca1\u6709\u76f8\u90bb\u539f\u503c"
            elif raw_value.casefold() in {value.casefold() for value in _METRIC_LOADING}:
                status, reason = "loading", "\u5b98\u65b9\u52a9\u624b\u5b57\u6bb5\u4ecd\u5728\u52a0\u8f7d"
            elif raw_value in _METRIC_PLACEHOLDERS:
                status, reason = "placeholder", None
            else:
                status, reason = "observed", None
        results.append(OperatingMetricData(key, status, raw_value if status in {"observed", "placeholder"} else None, _METRIC_SOURCE, offer_id, observed_at, reason))
    return results


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _contains_marker(value: str, markers: tuple[str, ...]) -> bool:
    value = value.casefold()
    return any(marker.casefold() in value for marker in markers)


def _is_login_page(page_url: str, title: str) -> bool:
    if _contains_marker(page_url, _LOGIN_URL_MARKERS):
        return True
    normalized_title = " ".join(title.casefold().split())
    return normalized_title in _LOGIN_TITLE_EXACT


def _is_verification_page(page: object, page_url: str, title: str) -> bool:
    if _contains_marker(page_url, _VERIFICATION_URL_MARKERS):
        return True
    normalized_title = " ".join(title.casefold().split())
    if normalized_title in _VERIFICATION_TITLE_EXACT:
        return True

    locator_factory = getattr(page, "locator", None)
    if not callable(locator_factory):
        return False
    for selector in _VERIFICATION_SELECTORS:
        try:
            locator = locator_factory(selector)
            if locator.count() and locator.first.is_visible():
                return True
        except Exception:
            continue

    try:
        punish = locator_factory(_BAXIA_PUNISH_SELECTOR)
        tips = locator_factory(_BAXIA_CAPTCHA_TIPS_SELECTOR)
        if (
            punish.count()
            and punish.first.is_visible()
            and tips.count()
            and tips.first.is_visible()
        ):
            text = " ".join(tips.first.inner_text().split())
            if any(marker in text for marker in _BAXIA_VERIFICATION_TEXTS):
                return True
    except Exception:
        pass
    return False


def _is_offline_page(page: object) -> bool:
    locator_factory = getattr(page, "locator", None)
    if not callable(locator_factory):
        return False
    try:
        locator = locator_factory(_OFFLINE_SELECTOR)
        if not locator.count() or not locator.first.is_visible():
            return False
        return " ".join(locator.first.inner_text().split()) == _OFFLINE_TEXT
    except Exception:
        return False


def _page_title(page: object) -> str:
    title = getattr(page, "title", None)
    if not callable(title):
        return ""
    try:
        value = title()
    except Exception:
        return ""
    return value if isinstance(value, str) else ""


def _check_page_access(page: object, status: int | None) -> None:
    page_url = page.url
    title = _page_title(page)
    if _is_verification_page(page, page_url, title):
        raise VerificationRequiredError("1688 verification is required")
    if _is_login_page(page_url, title):
        raise LoginRequiredError("1688 login is required")
    hostname = (urlparse(page_url).hostname or "").casefold()
    if hostname and not hostname.endswith(".1688.com") and hostname != "1688.com":
        raise PageUnavailableError("1688 redirected to an unavailable page")
    if _is_offline_page(page):
        raise OfflineProductDetected("1688 product is offline")
    if status is not None and status >= 400:
        raise PageUnavailableError("1688 page returned an unavailable status")


def _close_quietly(resource: object | None) -> None:
    if resource is None:
        return
    try:
        close = getattr(resource, "close", None)
        if close is not None:
            close()
    except Exception:
        pass


def _launch_context(playwright: object) -> object:
    chromium = getattr(playwright, "chromium")
    return chromium.launch_persistent_context(
        user_data_dir=str(_project_root() / ".browser-profile"),
        channel="chrome",
        headless=False,
        ignore_default_args=["--no-sandbox", "--disable-extensions"],
    )


def collect_1688_product_in_context(
    context: object,
    url: str,
    expected_offer_id: str,
    *,
    close_page: bool = False,
    keep_page_on_verification: bool = True,
) -> CollectionPageResult:
    """Collect base facts and visible assistant metrics from one product page visit."""
    pages = getattr(context, "pages", [])
    page = pages[0] if pages else context.new_page()
    keep_page = False
    try:
        try:
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=_NAVIGATION_TIMEOUT_MS,
            )
        except (PlaywrightTimeoutError, TimeoutError) as error:
            raise CollectionTimeoutError("1688 page navigation timed out") from error
        except PlaywrightError as error:
            raise PageUnavailableError("1688 page navigation failed") from error

        status = response.status if response is not None else None
        try:
            _check_page_access(page, status)
            page.wait_for_timeout(_VERIFICATION_RECHECK_DELAY_MS)
            _check_page_access(page, status)
        except VerificationRequiredError:
            keep_page = keep_page_on_verification
            raise

        try:
            html = page.content()
        except (PlaywrightTimeoutError, TimeoutError) as error:
            raise CollectionTimeoutError("1688 page content timed out") from error
        except PlaywrightError as error:
            raise PageUnavailableError("1688 page content was unavailable") from error

        url_match = re.fullmatch(r"/offer/(\d+)(?:\.html)?", urlparse(page.url).path)
        page_offer_id = parse_1688_offer_id(html)
        if not url_match or url_match.group(1) != expected_offer_id or page_offer_id != expected_offer_id:
            raise OfferIdMismatchError("offer_id mismatch: page identity does not match the monitored Offer")
        metrics = _assistant_metrics(page, expected_offer_id)
        try:
            product = parse_1688_html(html, expected_offer_id)
            product_error = None
        except Exception as error:
            product = None
            product_error = error
        return CollectionPageResult(expected_offer_id, product, product_error, metrics)
    finally:
        if close_page and not keep_page:
            _close_quietly(page)


def collect_1688_product(
    url: str,
    expected_offer_id: str,
    *,
    context: object | None = None,
) -> CollectionPageResult:
    """Collect one product, optionally reusing a caller-owned Context."""
    if context is not None:
        return collect_1688_product_in_context(
            context,
            url,
            expected_offer_id,
            close_page=False,
            keep_page_on_verification=True,
        )

    with sync_playwright() as playwright:
        owned_context = _launch_context(playwright)
        try:
            return collect_1688_product_in_context(
                owned_context,
                url,
                expected_offer_id,
                close_page=True,
                keep_page_on_verification=False,
            )
        finally:
            _close_quietly(owned_context)


def move_context_offscreen(context: object) -> object:
    """Move a headed Chromium window outside the visible desktop."""
    pages = getattr(context, "pages", [])
    page = pages[0] if pages else context.new_page()
    cdp = context.new_cdp_session(page)
    window = cdp.send("Browser.getWindowForTarget")
    window_id = window["windowId"]
    cdp.send(
        "Browser.setWindowBounds",
        {
            "windowId": window_id,
            "bounds": {"windowState": "normal", "left": -32000, "top": -32000},
        },
    )
    return page


def restore_context_window(context: object, page: object | None = None) -> None:
    """Restore a headed Chromium window for manual verification."""
    pages = getattr(context, "pages", [])
    target_page = page or (pages[0] if pages else context.new_page())
    cdp = context.new_cdp_session(target_page)
    window = cdp.send("Browser.getWindowForTarget")
    cdp.send(
        "Browser.setWindowBounds",
        {
            "windowId": window["windowId"],
            "bounds": {
                "windowState": "normal",
                "left": 40,
                "top": 60,
                "width": 1200,
                "height": 800,
            },
        },
    )
    bring_to_front = getattr(target_page, "bring_to_front", None)
    if callable(bring_to_front):
        bring_to_front()
