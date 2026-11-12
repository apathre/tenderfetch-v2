"""
scripts/purge_irrelevant_db_rows.py

One-time (re-runnable) cleanup: removes rows from Neon's `scraped_tenders`
that fail core/sector_filter.is_relevant() — the same power-sector test the
live scraper applies before writing — plus stale rows from list-only
sources with no deadline (PFCCL notices older than the newest
MAX_PFCCL_NOTICES; RECPDCL schemes with no document in
RECPDCL_MAX_AGE_DAYS).

Why this is needed: scripts/backfill_sheet_to_db.py (2026-08-17) copied the
whole Google Sheet into Neon, and the scraper itself ran unfiltered until
core/sector_filter.py landed (2026-08-28). Those non-power tenders (roads,
buildings, consultancy...) are what show up in TenderDesk Discovery.

Dry run by default — prints what WOULD be deleted. Pass --apply to delete.

Required env:
  DISCOVERY_DATABASE_URL  connection string for the tenderfetch-discovery Neon project

Usage:
  python scripts/purge_irrelevant_db_rows.py            # dry run
  python scripts/purge_irrelevant_db_rows.py --apply    # delete
"""

import argparse
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2  # noqa: E402

from core.sector_filter import SECTOR_FILTER_ENABLED, is_relevant  # noqa: E402
from scrapers.psu_list_scrapers import (  # noqa: E402
    MAX_PFCCL_NOTICES, RECPDCL_MAX_AGE_DAYS, latest_date_in)

# Same fields core/base_scraper.py feeds to is_relevant() (stage 2)
COLUMNS = (
    "title", "work_description", "tender_category", "product_category",
    "sub_category", "form_of_contract", "contract_type",
)
SAMPLE_SIZE = 25
DELETE_BATCH = 1000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually delete (default: dry run)")
    args = ap.parse_args()

    if not SECTOR_FILTER_ENABLED:
        sys.exit("SECTOR_FILTER_ENABLED is False — refusing to purge (every row would pass).")

    url = os.getenv("DISCOVERY_DATABASE_URL", "").strip()
    if not url:
        sys.exit("DISCOVERY_DATABASE_URL is not set.")

    conn = psycopg2.connect(url)
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT id, source_key, {', '.join(COLUMNS)} FROM scraped_tenders")
            rows = cur.fetchall()

        # list-only sources with no deadline on the page: rows that the
        # scraper's own recency rules would no longer pick up are stale
        with conn.cursor() as cur:
            cur.execute("SELECT id, source_key, tender_id, tender_detail_url FROM scraped_tenders "
                        "WHERE source_key IN ('PFCCL', 'RECPDCL')")
            listed = cur.fetchall()
        pf_ids = sorted((int(t.split("-")[1]) for _, k, t, _ in listed
                         if k == "PFCCL" and re.fullmatch(r"PFCCL-\d+", t or "")), reverse=True)
        pf_cut = pf_ids[MAX_PFCCL_NOTICES - 1] if len(pf_ids) >= MAX_PFCCL_NOTICES else 0
        stale = set()
        for row_id, key, tid, url in listed:
            if key == "PFCCL" and re.fullmatch(r"PFCCL-\d+", tid or "") and int(tid.split("-")[1]) < pf_cut:
                stale.add(row_id)
            if key == "RECPDCL":
                newest = latest_date_in(f"{tid} {url}")
                if newest and (datetime.now() - newest).days > RECPDCL_MAX_AGE_DAYS:
                    stale.add(row_id)

        doomed, per_source, kept = [], Counter(), 0
        samples = []
        for row in rows:
            row_id, source_key, *texts = row
            if row_id in stale:
                doomed.append(row_id)
                per_source[f"{source_key} (stale)"] += 1
                if len(samples) < SAMPLE_SIZE:
                    samples.append(f"  [{source_key} stale] {(texts[0] or '')[:100]}")
                continue
            if is_relevant(*(t or "" for t in texts)):
                kept += 1
                continue
            doomed.append(row_id)
            per_source[source_key] += 1
            if len(samples) < SAMPLE_SIZE:
                samples.append(f"  [{source_key}] {(texts[0] or '')[:110]}")

        print(f"Scanned {len(rows)} rows: {kept} relevant, {len(doomed)} not relevant")
        for key, n in per_source.most_common():
            print(f"  {key}: {n} to remove")
        if samples:
            print(f"\nSample of rows to remove (first {len(samples)}):")
            print("\n".join(samples))

        if not args.apply:
            print("\nDry run — nothing deleted. Re-run with --apply to delete.")
            return

        with conn.cursor() as cur:
            for i in range(0, len(doomed), DELETE_BATCH):
                cur.execute(
                    "DELETE FROM scraped_tenders WHERE id = ANY(%s::uuid[])",
                    ([str(x) for x in doomed[i:i + DELETE_BATCH]],),
                )
        conn.commit()
        print(f"\nDeleted {len(doomed)} rows.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
