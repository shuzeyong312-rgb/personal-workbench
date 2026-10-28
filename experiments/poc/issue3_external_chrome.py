"""Probe ordinary Chrome profile contention, using only a fresh temporary profile."""
import subprocess
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")


def main():
    with tempfile.TemporaryDirectory(prefix="issue3-chrome-") as directory:
        profile = Path(directory) / "profile"
        proc = subprocess.Popen([str(CHROME), f"--user-data-dir={profile}", "--no-first-run", "about:blank"])
        try:
            for _ in range(100):
                if (profile / "Local State").exists():
                    break
                if proc.poll() is not None:
                    raise RuntimeError("ordinary Chrome exited before readiness")
                time.sleep(0.1)
            else:
                raise RuntimeError("ordinary Chrome did not become ready")
            time.sleep(2)
            with sync_playwright() as p:
                try:
                    context = p.chromium.launch_persistent_context(
                        user_data_dir=str(profile), channel="chrome", headless=False,
                        ignore_default_args=["--no-sandbox", "--disable-extensions"], timeout=10000,
                    )
                except Exception as exc:
                    print(f"playwright_result={type(exc).__name__}; ordinary_alive={proc.poll() is None}")
                    assert proc.poll() is None
                else:
                    context.close()
                    raise AssertionError("Playwright started despite ordinary Chrome owning profile")
        finally:
            if proc.poll() is None:
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, check=False)
                proc.wait(timeout=10)


if __name__ == "__main__":
    main()
