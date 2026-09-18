from pathlib import Path

from playwright.sync_api import sync_playwright


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
        page.goto("https://www.1688.com/")
        page.goto("https://login.1688.com/member/signin.htm?Done=https%3A%2F%2Fwww.1688.com%2F")
        input("请在 Chrome 中手动登录 1688，完成后按 Enter 保存登录状态并关闭浏览器...")
        context.close()


if __name__ == "__main__":
    main()
