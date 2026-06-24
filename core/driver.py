"""
core/driver.py  –  Shared Chrome / undetected-chromedriver factory.
All scrapers call get_driver() instead of duplicating setup code.
"""

import re
import subprocess
import undetected_chromedriver as uc


def _get_chrome_major() -> int:
    raw = subprocess.check_output(["google-chrome", "--version"]).decode()
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
    return uc.Chrome(
        options=options,
        use_subprocess=True,
        version_main=_get_chrome_major(),
    )
