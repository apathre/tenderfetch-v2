"""
core/driver.py  –  Shared Chrome / undetected-chromedriver factory.
All scrapers call get_driver() instead of duplicating setup code.
"""

import os
import re
import shutil
import subprocess
import undetected_chromedriver as uc


def _find_chrome_binary() -> str:
    """Pick ONE Chrome binary deterministically.

    undetected_chromedriver's own finder iterates a Python *set* of candidate
    paths (google-chrome, chromium, chromium-browser, chrome, ...), so when a
    machine has more than one browser installed it may launch a different one
    than the one whose version we queried. Pinning the path avoids that.
    """
    override = os.getenv("CHROME_BIN", "").strip()
    if override and os.access(override, os.X_OK):
        return override
    for name in ("google-chrome-stable", "google-chrome"):
        path = shutil.which(name)
        if path:
            return path
    raise RuntimeError("Google Chrome not found on PATH")


def _get_chrome_major(binary: str) -> int:
    raw = subprocess.check_output([binary, "--version"]).decode()
    print(f"[driver] using {binary}: {raw.strip()}")
    m = re.search(r"(\d+)\.", raw)
    if not m:
        raise RuntimeError(f"Cannot parse Chrome version from: {raw!r}")
    return int(m.group(1))


def get_driver(headless: bool = True) -> uc.Chrome:
    """Return a configured undetected Chrome driver."""
    options = uc.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1366,768")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
    )
    binary = _find_chrome_binary()
    return uc.Chrome(
        options=options,
        use_subprocess=True,
        browser_executable_path=binary,
        version_main=_get_chrome_major(binary),
    )
