"""Observe persistent-context close after all temporary pages are closed."""
import tempfile
from playwright.sync_api import sync_playwright


def main():
    with tempfile.TemporaryDirectory(prefix="issue3-close-") as directory:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                directory, channel="chrome", headless=False,
                ignore_default_args=["--no-sandbox", "--disable-extensions"],
            )
            closed = []
            context.on("close", lambda _: closed.append(True))
            first = context.pages[0]
            second = context.new_page()
            first.close()
            assert not closed
            second.close()
            for _ in range(20):
                if closed:
                    break
                try:
                    playwright.chromium.connect_over_cdp("http://127.0.0.1:1", timeout=100)
                except Exception:
                    pass
            assert closed and not context.pages
            print("close_event=observed pages=0")
            context.close()


if __name__ == "__main__":
    main()
