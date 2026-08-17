"""
scripts/backfill_sheet_to_db.py

One-time backfill: copies every row already sitting in the Google Sheet
(across all configured source tabs) into the new `scraped_tenders` table in
Neon. Not part of the GitHub Actions workflow — run this once, locally,
after creating the Neon project and running database/scraped_tenders.sql
against it.

Required locally (same setup as a normal local scraper run — see README):
  - SERVICE_ACCOUNT_JSON   env var: full JSON content of the GCP service account key
  - DISCOVERY_DATABASE_URL env var: connection string for the new Neon project
  - sheets.json in repo root: { "SHEET_URL": "https://docs.google.com/..." }

Usage:
  python scripts/backfill_sheet_to_db.py
"""

import sys
from pathlib import Path

# db_writer/sheets_writer print "✓"/"✗" status lines — fine on GitHub Actions
# (Linux, UTF-8 stdout by default), but a Windows terminal's legacy cp1252
# codepage can't encode them and crashes mid-print, after the DB write/commit
# has already succeeded. Force UTF-8 stdout for local Windows runs of this script.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import FIXED_HEADERS, SOURCES
from output.db_writer import write_tenders_batch_db
from output.sheets_writer import _get_spreadsheet  # reuse existing auth/open logic

BATCH_SIZE = 500


def _rows_to_records(rows: list[list[str]]) -> list[dict]:
    records = []
    for row in rows:
        record = {h: (row[i] if i < len(row) else "") for i, h in enumerate(FIXED_HEADERS)}
        if record.get("Tender ID", "").strip():
            records.append(record)
    return records


def backfill_source(spreadsheet, source: dict) -> int:
    tab = source["sheet_tab"]
    try:
        ws = spreadsheet.worksheet(tab)
    except Exception:
        print(f"[Backfill] [{source['key']}] Tab '{tab}' not found — skipping")
        return 0

    all_values = ws.get_all_values()
    if len(all_values) <= 1:
        print(f"[Backfill] [{source['key']}] '{tab}' is empty — skipping")
        return 0

    header, rows = all_values[0], all_values[1:]
    if header != FIXED_HEADERS:
        print(f"[Backfill] [{source['key']}] '{tab}' header doesn't match FIXED_HEADERS — skipping")
        return 0

    records = _rows_to_records(rows)
    total = 0
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i:i + BATCH_SIZE]
        write_tenders_batch_db(source, batch)
        total += len(batch)
        print(f"[Backfill] [{source['key']}] {total}/{len(records)} rows upserted")

    return total


def main():
    spreadsheet = _get_spreadsheet()
    grand_total = 0
    for source in SOURCES:
        count = backfill_source(spreadsheet, source)
        grand_total += count
        print(f"[Backfill] [{source['key']}] done — {count} rows")

    print(f"\n[Backfill] Complete — {grand_total} total rows upserted into scraped_tenders")


if __name__ == "__main__":
    main()
