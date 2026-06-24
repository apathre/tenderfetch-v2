"""
main.py  –  Orchestrator
─────────────────────────
• Loads all enabled sources from config.SOURCES
• Spins up one Chrome driver per source (parallel via ThreadPoolExecutor)
• Merges all results and writes to Google Sheets

Speed gains vs. original:
  1. Parallel scraping across sources (ThreadPoolExecutor)
  2. Reduced sleep times (configurable per-source via timing constants in each scraper)
  3. driver.back() replaced with direct URL navigation (no extra page load)
  4. Pagination handled inside fetch_tender_list (no re-entry)
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
from output.sheets_writer import write_tenders


def _load_scraper_class(dotted_path: str):
    """Import a scraper class by its dotted module path."""
    module_path, class_name = dotted_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def _run_source(source: dict) -> list[dict]:
    """Instantiate a driver + scraper for one source and run it."""
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
        return []
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

    all_tenders: list[dict] = []

    # ── parallel execution across sources ───────────────────────────────────
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DRIVERS) as pool:
        futures = {pool.submit(_run_source, src): src["name"] for src in enabled}
        for future in as_completed(futures):
            src_name = futures[future]
            try:
                tenders = future.result()
                print(f"\n✓ {src_name}: {len(tenders)} tenders collected")
                all_tenders.extend(tenders)
            except Exception as exc:
                print(f"\n✗ {src_name}: unhandled exception – {exc}")

    print(f"\n{'='*60}")
    print(f"  Total tenders collected: {len(all_tenders)}")
    print(f"{'='*60}")

    write_tenders(all_tenders)
    print("\nDone.")


if __name__ == "__main__":
    main()
