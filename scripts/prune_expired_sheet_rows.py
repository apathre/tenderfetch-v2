"""
scripts/prune_expired_sheet_rows.py

Deletes rows from each source's Sheet tab whose "Bid Submission End Date"
is more than SHEETS_PRUNE_GRACE_DAYS in the past, and shrinks each tab's
reserved grid down to what it actually needs — keeps the shared workbook
under Google's 10M-cell-per-spreadsheet ceiling (already hit once: new
tabs started failing to create with "Invalid requests[0].addSheet: ...
above the limit of 10000000 cells").

Clearing cell VALUES alone doesn't free budget — Google's limit is on the
sheet's reserved grid dimensions (rows x cols), not how many cells hold
data. A tab created via _get_worksheet()'s `add_worksheet(rows=10000, ...)`
reserves that many rows regardless of how few ever get filled. This script
resizes the grid down after pruning, which is what actually recovers cells.

Neon (scraped_tenders) is completely untouched — it has no comparable
capacity constraint at this scale (tens of thousands of rows is a rounding
error against a 0.5GB Neon free-tier project) and remains the permanent,
complete record TenderDesk's Discovery feature reads from. This only trims
the best-effort Sheets mirror.

Run on a schedule via .github/workflows/prune_sheets.yml, or locally:
  python scripts/prune_expired_sheet_rows.py

Required locally (same setup as any other local run — see README):
  - SERVICE_ACCOUNT_JSON env var
  - sheets.json in repo root
"""

import sys
from datetime import date, timedelta
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import FIXED_HEADERS, SOURCES, SHEETS_PRUNE_GRACE_DAYS
from output.db_writer import _parse_deadline
from output.sheets_writer import _get_spreadsheet

_DEADLINE_COL = FIXED_HEADERS.index("Bid Submission End Date")
_BUFFER_ROWS = 200  # headroom so the next few scrape runs don't force an immediate re-grow


def prune_source(spreadsheet, source: dict, cutoff: date) -> int:
    tab = source["sheet_tab"]
    try:
        ws = spreadsheet.worksheet(tab)
    except Exception:
        print(f"[Prune] [{source['key']}] Tab '{tab}' not found — skipping")
        return 0

    all_values = ws.get_all_values()

    if len(all_values) <= 1:
        # Empty (or header-only) tab — still worth shrinking an over-provisioned grid
        target_rows = 1 + _BUFFER_ROWS
        if ws.row_count > target_rows:
            ws.resize(rows=target_rows, cols=len(FIXED_HEADERS))
            print(f"[Prune] [{source['key']}] '{tab}': empty — shrank grid to {target_rows} rows")
        else:
            print(f"[Prune] [{source['key']}] '{tab}': empty, grid already minimal — nothing to do")
        return 0

    header, rows = all_values[0], all_values[1:]
    if header != FIXED_HEADERS:
        print(f"[Prune] [{source['key']}] '{tab}' header doesn't match FIXED_HEADERS — skipping")
        return 0

    kept, dropped = [], 0
    for row in rows:
        raw = row[_DEADLINE_COL] if len(row) > _DEADLINE_COL else ""
        parsed = _parse_deadline(raw)
        # No parseable deadline -> keep. Never delete data we can't
        # confidently judge as expired.
        if parsed is None or parsed >= cutoff:
            kept.append(row)
        else:
            dropped += 1

    target_rows = len(kept) + 1 + _BUFFER_ROWS  # +1 header

    if dropped == 0 and ws.row_count <= target_rows:
        print(f"[Prune] [{source['key']}] '{tab}': nothing to prune ({len(rows)} rows, grid already right-sized)")
        return 0

    ws.clear()
    ws.resize(rows=target_rows, cols=len(FIXED_HEADERS))
    ws.append_row(FIXED_HEADERS)
    if kept:
        ws.append_rows(kept)

    print(f"[Prune] [{source['key']}] '{tab}': dropped {dropped} expired row(s), "
          f"kept {len(kept)}, grid resized to {target_rows} rows")
    return dropped


def main():
    cutoff = date.today() - timedelta(days=SHEETS_PRUNE_GRACE_DAYS)
    print(f"[Prune] Cutoff: deadlines before {cutoff.isoformat()} are eligible for removal "
          f"({SHEETS_PRUNE_GRACE_DAYS}-day grace period)")

    spreadsheet = _get_spreadsheet()
    total_dropped = 0
    for source in SOURCES:
        total_dropped += prune_source(spreadsheet, source, cutoff)

    print(f"\n[Prune] Complete — {total_dropped} row(s) removed across all tabs")


if __name__ == "__main__":
    main()
