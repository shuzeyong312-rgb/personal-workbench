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
    collect_1688_product,
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

    def title(self) -> str:
        return self.title_text

    def close(self) -> None:
        self.closed = True


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
