"""
output/sheets_writer.py
Writes tender records to Google Sheets, deduplicating by Tender ID + Source.
"""

import json
import os

import gspread
from google.oauth2.service_account import Credentials

from core.config import FIXED_HEADERS, GOOGLE_SCOPES, SHEETS_CONFIG_FILE, WORKSHEET_NAME


def _get_credentials() -> Credentials:
    sa_str = os.getenv("SERVICE_ACCOUNT_JSON")
    if not sa_str:
        raise ValueError(
            "SERVICE_ACCOUNT_JSON env var missing. "
            "Set it in GitHub Secrets (Actions) or your local environment."
        )
    info = json.loads(sa_str)
    return Credentials.from_service_account_info(info, scopes=GOOGLE_SCOPES)


def _get_sheet_url() -> str:
    if not os.path.exists(SHEETS_CONFIG_FILE):
        raise FileNotFoundError(f"{SHEETS_CONFIG_FILE} not found.")
    with open(SHEETS_CONFIG_FILE) as fh:
        cfg = json.load(fh)
    url = cfg.get("SHEET_URL")
    if not url:
        raise ValueError("SHEET_URL missing in sheets.json")
    return url


def write_tenders(tenders: list[dict]) -> None:
    if not tenders:
        print("[Sheets] No tenders to write.")
        return

    creds       = _get_credentials()
    client      = gspread.authorize(creds)
    sheet_url   = _get_sheet_url()
    spreadsheet = client.open_by_url(sheet_url)

    try:
        ws = spreadsheet.worksheet(WORKSHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(
            title=WORKSHEET_NAME, rows=5000, cols=len(FIXED_HEADERS)
        )
        print(f"[Sheets] Created worksheet '{WORKSHEET_NAME}'")

    # ensure correct headers
    current = ws.row_values(1)
    if current != FIXED_HEADERS:
        ws.clear()
        ws.append_row(FIXED_HEADERS)
        print(f"[Sheets] Headers written ({len(FIXED_HEADERS)} columns)")

    # build dedup set: Tender ID + Source Website
    existing = ws.get_all_values()
    try:
        id_col  = FIXED_HEADERS.index("Tender ID")
        src_col = FIXED_HEADERS.index("Source Website")
        existing_keys = {
            (row[id_col].strip(), row[src_col].strip())
            for row in existing[1:]
            if len(row) > max(id_col, src_col)
        }
    except ValueError:
        existing_keys = set()
        print("[Sheets] Warning: could not build dedup index")

    new_rows = []
    for t in tenders:
        key = (t.get("Tender ID", "").strip(), t.get("Source Website", "").strip())
        if not key[0]:
            print(f"[Sheets] Skipping row – no Tender ID")
            continue
        if key in existing_keys:
            continue
        new_rows.append([t.get(h, "") for h in FIXED_HEADERS])

    if new_rows:
        ws.append_rows(new_rows)
        print(f"[Sheets] ✓ Added {len(new_rows)} new rows  ({len(tenders)-len(new_rows)} duplicates skipped)")
    else:
        print("[Sheets] All tenders already exist – nothing new to add.")
