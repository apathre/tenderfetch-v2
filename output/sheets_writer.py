"""
output/sheets_writer.py

- write_tenders_batch()  : called per-org, appends immediately, to the
                           calling source's own worksheet tab (source["sheet_tab"])
- get_existing_ids()     : load known IDs at startup, scoped to that tab
- get_run_state()        : read last processed org index for this source's
                           row in the shared RunState tab (keyed by source["key"])
- save_run_state()       : save current org index to that same row
  So if Actions kills the job mid-run, next run resumes from where it stopped
  — independently per source, since each source has its own row.
"""

import json
import os

import gspread
from google.oauth2.service_account import Credentials

from core.config import FIXED_HEADERS, GOOGLE_SCOPES, SHEETS_CONFIG_FILE

STATE_WORKSHEET_NAME = "RunState"
STATE_HEADERS = ["source_key", "last_org_name", "last_org_index", "last_run"]

# ── module-level cache ───────────────────────────────────────────────────────
_spreadsheet_cache = None
_ws_cache: dict[str, gspread.Worksheet] = {}
_state_ws_cache    = None
_state_row_cache: dict[str, int] = {}   # source_key -> row number in RunState


def _get_credentials() -> Credentials:
    sa_str = os.getenv("SERVICE_ACCOUNT_JSON")
    if not sa_str:
        raise ValueError("SERVICE_ACCOUNT_JSON env var missing.")
    return Credentials.from_service_account_info(json.loads(sa_str), scopes=GOOGLE_SCOPES)


def _get_sheet_url() -> str:
    if not os.path.exists(SHEETS_CONFIG_FILE):
        raise FileNotFoundError(f"{SHEETS_CONFIG_FILE} not found.")
    # utf-8-sig strips a leading BOM if present (e.g. from PowerShell's
    # `Out-File -Encoding utf8`, which always writes one) and is a no-op
    # otherwise — plain `open()` chokes on that BOM with a confusing
    # "Expecting value: line 1 column 1" JSONDecodeError.
    with open(SHEETS_CONFIG_FILE, encoding='utf-8-sig') as fh:
        cfg = json.load(fh)
    url = cfg.get("SHEET_URL")
    if not url:
        raise ValueError("SHEET_URL missing in sheets.json")
    return url


def _get_spreadsheet() -> gspread.Spreadsheet:
    global _spreadsheet_cache
    if _spreadsheet_cache is None:
        creds = _get_credentials()
        client = gspread.authorize(creds)
        _spreadsheet_cache = client.open_by_url(_get_sheet_url())
    return _spreadsheet_cache


def _get_worksheet(sheet_tab: str) -> gspread.Worksheet:
    """Get (or create) the worksheet tab for one source. Cached per tab name."""
    if sheet_tab in _ws_cache:
        return _ws_cache[sheet_tab]

    spreadsheet = _get_spreadsheet()
    try:
        ws = spreadsheet.worksheet(sheet_tab)
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(
            title=sheet_tab, rows=10000, cols=len(FIXED_HEADERS)
        )
        print(f"[Sheets] Created worksheet '{sheet_tab}'")

    current = ws.row_values(1)
    if current != FIXED_HEADERS:
        ws.clear()
        ws.append_row(FIXED_HEADERS)
        print(f"[Sheets] Headers written to '{sheet_tab}' ({len(FIXED_HEADERS)} columns)")

    _ws_cache[sheet_tab] = ws
    return ws


def _get_state_worksheet() -> gspread.Worksheet:
    global _state_ws_cache
    if _state_ws_cache is not None:
        return _state_ws_cache

    spreadsheet = _get_spreadsheet()
    try:
        ws = spreadsheet.worksheet(STATE_WORKSHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(
            title=STATE_WORKSHEET_NAME, rows=50, cols=len(STATE_HEADERS)
        )
        ws.append_row(STATE_HEADERS)
        print(f"[Sheets] Created worksheet '{STATE_WORKSHEET_NAME}'")

    if ws.row_values(1) != STATE_HEADERS:
        # migrate from the old single-row (no source_key) schema, or fix a
        # mismatched header — safe no-op if it's already correct.
        ws.update("A1", [STATE_HEADERS])
        print(f"[Sheets] '{STATE_WORKSHEET_NAME}' header set to {STATE_HEADERS}")

    _state_ws_cache = ws
    return ws


def _find_or_create_state_row(source_key: str) -> int:
    """Return the 1-indexed row number holding this source's run state,
    creating a new row for it if one doesn't exist yet."""
    if source_key in _state_row_cache:
        return _state_row_cache[source_key]

    ws = _get_state_worksheet()
    keys = ws.col_values(1)[1:]  # skip header row
    if source_key in keys:
        row = keys.index(source_key) + 2  # +1 for header, +1 for 1-indexing
    else:
        ws.append_row([source_key, "", 0, ""])
        row = len(keys) + 2
        print(f"[Sheets] Created RunState row for '{source_key}'")

    _state_row_cache[source_key] = row
    return row


# ── public API ───────────────────────────────────────────────────────────────

def get_existing_ids(source: dict) -> set[str]:
    """Load all known Tender IDs from this source's own worksheet tab.

    Never raises — Sheets is a best-effort mirror, not the source of truth
    (scraped_tenders in Neon is). A Sheets failure here (e.g. the shared
    workbook hitting Google's 10M-cell-per-spreadsheet ceiling, which
    happens when trying to create a brand-new tab for a new source) must
    never stop a run before it's even fetched a tender. Returning an empty
    set just means this run treats everything as "new" — Neon's own
    UNIQUE(source_key, tender_id) upsert still prevents duplicate rows
    there even if nothing gets deduped Sheets-side.
    """
    try:
        ws = _get_worksheet(source["sheet_tab"])
        id_col = FIXED_HEADERS.index("Tender ID")
        all_rows = ws.get_all_values()[1:]
        ids = {
            row[id_col].strip()
            for row in all_rows
            if len(row) > id_col and row[id_col].strip()
        }
        print(f"[Sheets] [{source['key']}] Loaded {len(ids)} existing Tender IDs")
        return ids
    except Exception as e:
        print(f"[Sheets] [{source.get('key')}] Warning: could not load existing IDs – {e}")
        return set()


def write_tenders_batch(source: dict, tenders: list[dict]) -> None:
    """Append a batch of tenders (typically one org's worth) to this
    source's worksheet tab immediately.

    Never raises, same reasoning as get_existing_ids() above — a Sheets
    failure (e.g. the workbook-wide cell cap) must not prevent the
    Neon write in base_scraper.py's caller from running.
    """
    if not tenders:
        return

    try:
        ws = _get_worksheet(source["sheet_tab"])
        new_rows = [
            [t.get(h, "") for h in FIXED_HEADERS]
            for t in tenders
            if t.get("Tender ID", "").strip()
        ]

        if new_rows:
            ws.append_rows(new_rows)
            print(f"[Sheets] [{source['key']}] ✓ Written {len(new_rows)} tender(s) to '{source['sheet_tab']}'")
        else:
            print(f"[Sheets] [{source.get('key')}] No rows to write — all missing Tender ID")
    except Exception as e:
        print(f"[Sheets] [{source.get('key')}] Warning: could not write batch – {e}")


def get_run_state(source: dict) -> tuple[int, str]:
    """
    Returns (last_org_index, last_org_name) for this source.
    last_org_index is the index of the last ORG that was fully processed.
    Next run for this source should start from last_org_index + 1.
    """
    try:
        ws = _get_state_worksheet()
        row = _find_or_create_state_row(source["key"])
        values = ws.row_values(row)
        idx = int(values[2]) if len(values) > 2 and values[2].strip().isdigit() else 0
        name = values[1] if len(values) > 1 else ""
        print(f"[Sheets] [{source['key']}] Resuming from org index {idx} ('{name}')")
        return idx, name
    except Exception as e:
        print(f"[Sheets] [{source.get('key')}] Could not read run state – starting from 0. ({e})")
        return 0, ""


def save_run_state(source: dict, org_index: int, org_name: str, run_time: str) -> None:
    """Save the index of the last fully-processed org for this source."""
    try:
        ws = _get_state_worksheet()
        row = _find_or_create_state_row(source["key"])
        ws.update(f"A{row}:D{row}", [[source["key"], org_name, org_index, run_time]])
    except Exception as e:
        print(f"[Sheets] [{source.get('key')}] Warning: could not save run state – {e}")
