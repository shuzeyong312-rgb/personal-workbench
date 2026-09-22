from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from app.collection.parser_1688 import parse_1688_html
from app.collection.types import ProductData


class CollectorError(RuntimeError):
    """Base class for stable Playwright collection errors."""


class LoginRequiredError(CollectorError):
    """The persistent 1688 session is no longer logged in."""


class VerificationRequiredError(CollectorError):
    """1688 requires a verification or risk-control step."""


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
    if status is not None and status >= 400:
        raise PageUnavailableError("1688 page returned an unavailable status")

    hostname = (urlparse(page_url).hostname or "").casefold()
    if hostname and not hostname.endswith(".1688.com") and hostname != "1688.com":
        raise PageUnavailableError("1688 redirected to an unavailable page")


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
        ignore_default_args=["--no-sandbox"],
    )


def collect_1688_product_in_context(
    context: object,
    url: str,
    expected_offer_id: str,
    *,
    close_page: bool = False,
    keep_page_on_verification: bool = True,
) -> ProductData:
    """Collect one product without closing caller-owned Context resources."""
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

        return parse_1688_html(html, expected_offer_id)
    finally:
        if close_page and not keep_page:
            _close_quietly(page)


def collect_1688_product(
    url: str,
    expected_offer_id: str,
    *,
    context: object | None = None,
) -> ProductData:
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
