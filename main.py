"""
main.py  –  Orchestrator

Runs all enabled sources. Each source scraper:
  - Resumes from last saved org index (survives GitHub Actions 1hr kill)
  - Writes to Google Sheets after every org (nothing lost on timeout)
  - Skips orgs where no new tenders exist (incremental runs are fast)
"""

import importlib
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.config import (
    MAX_CONCURRENT_DRIVERS,
    MAX_ORGANIZATIONS_TO_PROCESS,
    MAX_TENDERS_PER_ORG,
    SOURCES,
)
from core.driver import get_driver


def _load_scraper_class(dotted_path: str):
    module_path, class_name = dotted_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def _run_source(source: dict) -> int:
    """Run one source — returns count of new tenders written."""
    name = source["name"]
    print(f"\n{'='*60}")
    print(f"  Starting: {name}")
    print(f"{'='*60}")

    driver = get_driver(headless=True)
    try:
        ScraperClass = _load_scraper_class(source["scraper"])
        scraper = ScraperClass(driver=driver, source=source)
        return scraper.scrape(
            max_orgs=MAX_ORGANIZATIONS_TO_PROCESS,
            max_per_org=MAX_TENDERS_PER_ORG,
        )
    except Exception as exc:
        print(f"[{name}] FATAL: {exc}")
        return 0
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def main():
    enabled = [s for s in SOURCES if s.get("enabled", True)]

    if not enabled:
        print("No enabled sources in config.SOURCES. Exiting.")
        sys.exit(0)

    print(f"Running {len(enabled)} source(s) with up to {MAX_CONCURRENT_DRIVERS} parallel drivers")

    total = 0
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DRIVERS) as pool:
        futures = {pool.submit(_run_source, src): src["name"] for src in enabled}
        for future in as_completed(futures):
            src_name = futures[future]
            try:
                count = future.result()
                print(f"\n✓ {src_name}: {count} new tenders written this run")
                total += count
            except Exception as exc:
                print(f"\n✗ {src_name}: unhandled exception – {exc}")

    print(f"\n{'='*60}")
    print(f"  Total new tenders written this run: {total}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
