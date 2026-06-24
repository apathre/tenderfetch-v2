"""
output/sheets_writer.py

Changes:
- write_tenders_batch()  : called per-org, appends immediately
- get_existing_ids()     : load known IDs at startup
- get_run_state()        : read last processed org index from RunState tab
- save_run_state()       : save current org index to RunState tab
  So if Actions kills the job mid-run, next run resumes from where it stopped.
"""

import json
import os

import gspread
from google.oauth2.service_account import Credentials

from core.config import FIXED_HEADERS, GOOGLE_SCOPES, SHEETS_CONFIG_FILE, WORKSHEET_NAME

STATE_WORKSHEET_NAME = "RunState"

# ── module-level cache ───────────────────────────────────────────────────────
_spreadsheet_cache = None
_ws_cache          = None
_state_ws_cache    = None


def _get_credentials() -> Credentials:
    sa_str = os.getenv("SERVICE_ACCOUNT_JSON")
    if not sa_str:
        raise ValueError("SERVICE_ACCOUNT_JSON env var missing.")
    return Credentials.from_service_account_info(json.loads(sa_str), scopes=GOOGLE_SCOPES)


def _get_sheet_url() -> str:
    if not os.path.exists(SHEETS_CONFIG_FILE):
        raise FileNotFoundError(f"{SHEETS_CONFIG_FILE} not found.")
    with open(SHEETS_CONFIG_FILE) as fh:
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


def _get_worksheet() -> gspread.Worksheet:
    global _ws_cache
    if _ws_cache is not None:
        return _ws_cache

    spreadsheet = _get_spreadsheet()
    try:
        ws = spreadsheet.worksheet(WORKSHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(
            title=WORKSHEET_NAME, rows=10000, cols=len(FIXED_HEADERS)
        )
        print(f"[Sheets] Created worksheet '{WORKSHEET_NAME}'")

    current = ws.row_values(1)
    if current != FIXED_HEADERS:
        ws.clear()
        ws.append_row(FIXED_HEADERS)
        print(f"[Sheets] Headers written ({len(FIXED_HEADERS)} columns)")

    _ws_cache = ws
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
            title=STATE_WORKSHEET_NAME, rows=10, cols=3
        )
        ws.append_row(["last_org_index", "last_org_name", "last_run"])
        ws.append_row([0, "", ""])
        print(f"[Sheets] Created worksheet '{STATE_WORKSHEET_NAME}'")

    _state_ws_cache = ws
    return ws


# ── public API ───────────────────────────────────────────────────────────────

def get_existing_ids(source_name: str) -> set[str]:
    """Load all known Tender IDs for a source from the sheet."""
    ws = _get_worksheet()
    try:
        id_col  = FIXED_HEADERS.index("Tender ID")
        src_col = FIXED_HEADERS.index("Source Website")
        all_rows = ws.get_all_values()[1:]
        ids = {
            row[id_col].strip()
            for row in all_rows
            if len(row) > max(id_col, src_col)
            and row[src_col].strip() == source_name
            and row[id_col].strip()
        }
        print(f"[Sheets] Loaded {len(ids)} existing Tender IDs for '{source_name}'")
        return ids
    except Exception as e:
        print(f"[Sheets] Warning: could not load existing IDs – {e}")
        return set()


def write_tenders_batch(tenders: list[dict]) -> None:
    """
    
    """
    if not tenders:
        return

    ws = _get_worksheet()
    new_rows = [
        [t.get(h, "") for h in FIXED_HEADERS]
        for t in tenders
        if t.get("Tender ID", "").strip()
    ]
    
    if new_rows:
        ws.append_rows(new_rows)
        print(f"[Sheets] ✓ Written {len(new_rows)} tender(s) to sheet")
    else:
        print(f"[Sheets] No rows to write — all missing Tender ID")


def get_run_state() -> tuple[int, str]:
    """
    Returns (last_org_index, last_org_name).
    last_org_index is the index of the last ORG that was fully processed.
    Next run should start from last_org_index + 1.
    """
    try:
        ws = _get_state_worksheet()
        row = ws.row_values(2)   # row 1 = header, row 2 = state
        if not row or not row[0]:
            return 0, ""
        idx  = int(row[0]) if row[0].strip().isdigit() else 0
        name = row[1] if len(row) > 1 else ""
        print(f"[Sheets] Resuming from org index {idx} ('{name}')")
        return idx, name
    except Exception as e:
        print(f"[Sheets] Could not read run state – starting from 0. ({e})")
        return 0, ""


def save_run_state(org_index: int, org_name: str, run_time: str) -> None:
    """Save the index of the last fully-processed org."""
    try:
        ws = _get_state_worksheet()
        ws.update("A2:C2", [[org_index, org_name, run_time]])
    except Exception as e:
        print(f"[Sheets] Warning: could not save run state – {e}")
