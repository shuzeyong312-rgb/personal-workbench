from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app.collection.collector_1688 import (
    CollectionTimeoutError,
    LoginRequiredError,
    PageUnavailableError,
    VerificationRequiredError,
    _is_verification_page,
    collect_1688_product,
    collect_1688_product_in_context,
)
from app.collection.parser_1688 import (
    CollectionParseError,
    OfferIdMismatchError,
    parse_1688_html,
)


FIXTURES = Path(__file__).parent / "fixtures"
PRODUCT_URL = "https://detail.1688.com/offer/1081895898799.html"


class FakePage:
    def __init__(
        self,
        html: str = "",
        url: str = PRODUCT_URL,
        response_status: int = 200,
        title_text: str = "脱敏商品",
    ):
        self.html = html
        self.url = url
        self.response_status = response_status
        self.title_text = title_text
        self.goto_args = None
        self.closed = False
        self.content_error = None
        self.goto_error = None
        self.wait_for_timeout_calls: list[int] = []

    def goto(self, url: str, **kwargs):
        self.goto_args = (url, kwargs)
        if self.goto_error:
            raise self.goto_error
        self.url = self.url or url
        return SimpleNamespace(status=self.response_status)

    def content(self) -> str:
        if self.content_error:
            raise self.content_error
        return self.html

    def wait_for_timeout(self, timeout_ms: int) -> None:
        self.wait_for_timeout_calls.append(timeout_ms)

    def title(self) -> str:
        return self.title_text

    def close(self) -> None:
        self.closed = True


class FakeLocator:
    def __init__(self, page: "SelectorPage", selector: str):
        self.page = page
        self.selector = selector
        self.first = self

    def count(self) -> int:
        return int(self.selector in self.page.selector_states)

    def is_visible(self) -> bool:
        return self.page.selector_states[self.selector][0]

    def inner_text(self) -> str:
        return self.page.selector_states[self.selector][1]


class SelectorPage(FakePage):
    def __init__(self, *args, selector_states=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.selector_states = selector_states or {}
        self.on_wait = None

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, selector)

    def wait_for_timeout(self, timeout_ms: int) -> None:
        super().wait_for_timeout(timeout_ms)
        if self.on_wait is not None:
            self.on_wait()


class FakeContext:
    def __init__(self, page: FakePage):
        self.pages = [page]
        self.closed = False

    def new_page(self):
        page = FakePage()
        self.pages.append(page)
        return page

    def close(self) -> None:
        self.closed = True


class FakePlaywright:
    def __init__(self, context: FakeContext):
        self.context = context
        self.launch_args = None
        self.chromium = self
        self.stopped = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.stopped = True

    def launch_persistent_context(self, **kwargs):
        self.launch_args = kwargs
        return self.context


def fake_runtime(page: FakePage):
    context = FakeContext(page)
    playwright = FakePlaywright(context)
    return playwright, context


class LifecyclePage(FakePage):
    def __init__(self, context: "LifecycleContext"):
        super().__init__()
        self.context = context
        self.goto_urls: list[str] = []

    def goto(self, url: str, **kwargs):
        self.goto_urls.append(url)
        self.url = url
        return super().goto(url, **kwargs)

    def close(self) -> None:
        self.closed = True
        if self in self.context.pages:
            self.context.pages.remove(self)
        if not self.context.pages:
            self.context.closed = True


class LifecycleContext:
    def __init__(self):
        self.closed = False
        self.pages: list[LifecyclePage] = []
        self.page = LifecyclePage(self)
        self.pages.append(self.page)

    def new_page(self):
        if self.closed:
            raise RuntimeError("Context closed after its last Page was closed")
        page = LifecyclePage(self)
        self.pages.append(page)
        return page

    def close(self) -> None:
        self.closed = True
        for page in list(self.pages):
            page.closed = True
        self.pages.clear()


def test_shared_context_can_collect_two_products_without_closing_caller_page() -> None:
    context = LifecycleContext()
    with patch(
        "app.collection.collector_1688.parse_1688_html",
        side_effect=lambda _html, expected_offer_id: SimpleNamespace(
            offer_id=expected_offer_id
        ),
    ):
        first = collect_1688_product_in_context(
            context,
            "https://detail.1688.com/offer/1.html",
            "1",
        )
        second = collect_1688_product_in_context(
            context,
            "https://detail.1688.com/offer/2.html",
            "2",
        )

    assert first.offer_id == "1"
    assert second.offer_id == "2"
    assert context.page.goto_urls == [
        "https://detail.1688.com/offer/1.html",
        "https://detail.1688.com/offer/2.html",
    ]
    assert not context.page.closed
    context.close()
    assert context.page.closed


def test_shared_context_keeps_verification_page_for_manual_recovery() -> None:
    context = LifecycleContext()
    context.page.title_text = "滑动验证"

    with pytest.raises(VerificationRequiredError):
        collect_1688_product_in_context(
            context,
            "https://detail.1688.com/offer/1.html",
            "1",
        )

    assert context.pages == [context.page]
    assert not context.page.closed
    context.close()


def test_visible_nc_wrapper_is_detected_before_content_read() -> None:
    page = SelectorPage(
        (FIXTURES / "normal_product.html").read_text(encoding="utf-8"),
        selector_states={"#nc_1_wrapper": (True, "")},
    )
    page.content_error = PlaywrightError("content should not be read")
    context = FakeContext(page)

    with pytest.raises(VerificationRequiredError):
        collect_1688_product_in_context(context, PRODUCT_URL, "1081895898799")

    assert page.wait_for_timeout_calls == []


@pytest.mark.parametrize(
    ("page_url", "title"),
    [
        ("https://detail.1688.com/offer/1.html?verify=1", "普通页面"),
        (PRODUCT_URL, "滑动验证"),
    ],
)
def test_existing_verification_url_and_title_signals_remain(page_url: str, title: str) -> None:
    page = FakePage(url=page_url, title_text=title)

    assert _is_verification_page(page, page_url, title)


def test_visible_baxia_punish_with_captcha_tips_is_verification() -> None:
    page = SelectorPage(
        title_text="验证码拦截",
        selector_states={
            "#baxia-punish": (True, ""),
            "#baxia-punish .captcha-tips": (True, "亲，请拖动下方滑块完成验证"),
        },
    )

    assert _is_verification_page(page, PRODUCT_URL, page.title())


def test_invisible_baxia_captcha_tips_is_not_verification() -> None:
    page = SelectorPage(
        selector_states={
            "#baxia-punish": (True, ""),
            "#baxia-punish .captcha-tips": (False, "亲，请拖动下方滑块完成验证"),
        },
    )

    assert not _is_verification_page(page, PRODUCT_URL, page.title())


@pytest.mark.parametrize(
    "html",
    [
        (FIXTURES / "normal_product.html").read_text(encoding="utf-8"),
        '<h3 class="mod-detail-offline-title">商品已下架</h3>',
    ],
)
def test_normal_and_offline_pages_do_not_match_baxia_verification(html: str) -> None:
    page = SelectorPage(html)

    assert not _is_verification_page(page, PRODUCT_URL, page.title())


def test_verification_appearing_after_300ms_is_detected() -> None:
    page = SelectorPage(
        (FIXTURES / "normal_product.html").read_text(encoding="utf-8"),
        selector_states={},
    )
    page.on_wait = lambda: page.selector_states.update(
        {
            "#baxia-punish": (True, ""),
            "#baxia-punish .captcha-tips": (True, "通过验证以确保正常访问"),
        }
    )
    context = FakeContext(page)

    with pytest.raises(VerificationRequiredError):
        collect_1688_product_in_context(context, PRODUCT_URL, "1081895898799")

    assert page.wait_for_timeout_calls == [300]


def test_second_verification_check_is_single_and_bounded() -> None:
    page = SelectorPage((FIXTURES / "normal_product.html").read_text(encoding="utf-8"))
    context = FakeContext(page)

    with patch(
        "app.collection.collector_1688.parse_1688_html",
        return_value=SimpleNamespace(offer_id="1081895898799"),
    ):
        result = collect_1688_product_in_context(context, PRODUCT_URL, "1081895898799")

    assert result.offer_id == "1081895898799"
    assert page.wait_for_timeout_calls == [300]


def test_collects_html_and_passes_expected_offer_id() -> None:
    page = FakePage((FIXTURES / "normal_product.html").read_text(encoding="utf-8"))
    playwright, context = fake_runtime(page)

    with patch("app.collection.collector_1688.sync_playwright", return_value=playwright):
        with patch(
            "app.collection.collector_1688.parse_1688_html",
            wraps=parse_1688_html,
        ) as parser:
            result = collect_1688_product(PRODUCT_URL, "1081895898799")

    assert result.offer_id == "1081895898799"
    assert parser.call_args.args == (page.html, "1081895898799")
    assert playwright.launch_args == {
        "user_data_dir": str(Path(__file__).resolve().parents[2] / ".browser-profile"),
        "channel": "chrome",
        "headless": False,
        "ignore_default_args": ["--no-sandbox"],
    }
    assert page.goto_args == (
        PRODUCT_URL,
        {"wait_until": "domcontentloaded", "timeout": 30_000},
    )
    assert page.closed and context.closed and playwright.stopped


@pytest.mark.parametrize(
    ("page_url", "html", "error_type"),
    [
        ("https://login.1688.com/member/signin.htm", "", LoginRequiredError),
        (PRODUCT_URL, "", VerificationRequiredError),
    ],
)
def test_detects_login_and_verification_pages(page_url, html, error_type) -> None:
    title = "滑动验证" if error_type is VerificationRequiredError else "登录"
    page = FakePage(html, url=page_url, title_text=title)
    playwright, context = fake_runtime(page)

    with patch("app.collection.collector_1688.sync_playwright", return_value=playwright):
        with pytest.raises(error_type):
            collect_1688_product(PRODUCT_URL, "1081895898799")

    assert page.closed and context.closed and playwright.stopped


def test_navigation_timeout_is_stable_and_closes_resources() -> None:
    page = FakePage()
    page.goto_error = PlaywrightTimeoutError("timeout")
    playwright, context = fake_runtime(page)

    with patch("app.collection.collector_1688.sync_playwright", return_value=playwright):
        with pytest.raises(CollectionTimeoutError):
            collect_1688_product(PRODUCT_URL, "1081895898799")

    assert page.closed and context.closed and playwright.stopped


def test_content_error_is_unavailable_and_closes_resources() -> None:
    page = FakePage()
    page.content_error = PlaywrightError("content failed")
    playwright, context = fake_runtime(page)

    with patch("app.collection.collector_1688.sync_playwright", return_value=playwright):
        with pytest.raises(PageUnavailableError):
            collect_1688_product(PRODUCT_URL, "1081895898799")

    assert page.closed and context.closed and playwright.stopped


def test_normal_product_text_containing_verification_word_reaches_parser() -> None:
    html = (
        (FIXTURES / "normal_product.html").read_text(encoding="utf-8")
        + "<p>商品说明：验证码仅用于示例文字</p>"
    )
    page = FakePage(html, title_text="商品验证码说明")
    playwright, context = fake_runtime(page)

    with patch("app.collection.collector_1688.sync_playwright", return_value=playwright):
        result = collect_1688_product(PRODUCT_URL, "1081895898799")

    assert result.offer_id == "1081895898799"
    assert page.closed and context.closed and playwright.stopped


def test_parser_exception_keeps_original_semantics_and_closes_resources() -> None:
    page = FakePage((FIXTURES / "malformed_product.html").read_text(encoding="utf-8"))
    playwright, context = fake_runtime(page)

    with patch("app.collection.collector_1688.sync_playwright", return_value=playwright):
        with pytest.raises(CollectionParseError, match="missing required product fields"):
            collect_1688_product(PRODUCT_URL, "3000000000000")

    assert page.closed and context.closed and playwright.stopped


def test_offer_id_mismatch_exception_keeps_original_semantics() -> None:
    page = FakePage((FIXTURES / "normal_product.html").read_text(encoding="utf-8"))
    playwright, context = fake_runtime(page)

    with patch("app.collection.collector_1688.sync_playwright", return_value=playwright):
        with pytest.raises(OfferIdMismatchError, match="offer_id mismatch"):
            collect_1688_product(PRODUCT_URL, "other-offer")

    assert page.closed and context.closed and playwright.stopped
