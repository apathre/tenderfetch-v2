"""
output/db_writer.py

Writes the same scraped batches to Neon Postgres — a separate, dedicated
project from tenderdesk-backend's production database — alongside the
existing Google Sheets write in output/sheets_writer.py. This is the table
TenderDesk's "Discovery" feature queries; Sheets keeps working exactly as it
does today as a backup / audit trail.

- write_tenders_batch_db() : upserts a batch (ON CONFLICT source_key+tender_id
                              DO UPDATE), so re-scraping an already-seen
                              tender (e.g. after a corrigendum) refreshes it
                              instead of erroring or duplicating. No separate
                              "known ids" tracking is needed here —
                              sheets_writer.get_existing_ids() remains the
                              single source of truth for what counts as
                              "new" during a scrape run.
"""

import os
from datetime import datetime

import psycopg2
import psycopg2.extras

from core.config import FIXED_HEADERS

# FIXED_HEADERS (sheet column) -> scraped_tenders column (see database/scraped_tenders.sql)
_HEADER_TO_COLUMN = {
    "Source Website":                     "source_website",
    "Fetch Date":                         "fetch_date",
    "Organisation":                       "organisation",
    "Tender Count":                       "tender_count",
    "Organization Chain":                 "organization_chain",
    "Tender Reference Number":            "tender_reference_number",
    "Tender ID":                          "tender_id",
    "Tender Type":                        "tender_type",
    "Tender Category":                    "tender_category",
    "Form of Contract":                   "form_of_contract",
    "Tender Fee in Rs":                   "tender_fee_in_rs",
    "Tender Fee Exemption Allowed":       "tender_fee_exemption_allowed",
    "EMD Amount in Rs":                   "emd_amount_in_rs",
    "EMD Exemption Allowed":              "emd_exemption_allowed",
    "EMD Fee Type":                       "emd_fee_type",
    "Title":                              "title",
    "Work Description":                   "work_description",
    "NDA/Pre Qualification":              "nda_pre_qualification",
    "Tender Value in Rs":                 "tender_value_in_rs",
    "Contract Type":                      "contract_type",
    "Location":                           "location",
    "Product Category":                   "product_category",
    "Sub Category":                       "sub_category",
    "Bid Validity(Days)":                 "bid_validity_days",
    "Period of Work(Days)":               "period_of_work_days",
    "Pre Bid Meeting Place":              "pre_bid_meeting_place",
    "Pre Bid Meeting Address":            "pre_bid_meeting_address",
    "Pre Bid Meeting Date":               "pre_bid_meeting_date",
    "Bid Opening Place":                  "bid_opening_place",
    "Published Date":                     "published_date",
    "Bid Opening Date":                   "bid_opening_date",
    "Document Download / Sale Start Date": "document_download_sale_start_date",
    "Document Download / Sale End Date":  "document_download_sale_end_date",
    "Clarification Start Date":           "clarification_start_date",
    "Clarification End Date":             "clarification_end_date",
    "Bid Submission Start Date":          "bid_submission_start_date",
    "Bid Submission End Date":            "bid_submission_end_date",
    "Tender Inviting Authority Name":     "tender_inviting_authority_name",
    "Tender Inviting Authority Address":  "tender_inviting_authority_address",
    "Tender Detail URL":                  "tender_detail_url",
}

assert set(_HEADER_TO_COLUMN) == set(FIXED_HEADERS), (
    "output/db_writer.py's _HEADER_TO_COLUMN is out of sync with "
    "core.config.FIXED_HEADERS — update both together."
)

# NIC eProcure / GePNIC portals render dates like "17-Aug-2026 05:00 PM";
# try a few known variants, otherwise leave deadline_at NULL (the raw text
# is always kept in bid_submission_end_date regardless).
_DATE_FORMATS = ("%d-%b-%Y %I:%M %p", "%d-%b-%Y", "%d/%m/%Y %I:%M %p", "%d/%m/%Y")


def _parse_deadline(raw: str):
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


_connection = None


def _get_connection():
    global _connection
    if _connection is None or _connection.closed:
        dsn = os.getenv("DISCOVERY_DATABASE_URL")
        if not dsn:
            raise ValueError("DISCOVERY_DATABASE_URL env var missing.")
        _connection = psycopg2.connect(dsn)
    return _connection


def write_tenders_batch_db(source: dict, tenders: list[dict]) -> None:
    """Upsert a batch (typically one org's worth) into scraped_tenders.
    Same call signature as sheets_writer.write_tenders_batch() so
    core/base_scraper.py can call both the same way."""
    rows = [t for t in tenders if t.get("Tender ID", "").strip()]
    if not rows:
        return

    sheet_columns  = list(_HEADER_TO_COLUMN.values())
    insert_columns = sheet_columns + ["source_key", "deadline_at"]
    text_update_columns = [c for c in sheet_columns if c != "tender_id"]

    values = []
    for t in rows:
        row = [t.get(header, "") or None for header in FIXED_HEADERS]
        row.append(source["key"])
        row.append(_parse_deadline(t.get("Bid Submission End Date", "")))
        values.append(row)

    placeholders = "(" + ", ".join(["%s"] * len(insert_columns)) + ")"
    # COALESCE(NULLIF(...)) rather than a plain overwrite: a re-check pass
    # (see get_soon_to_expire()) fetches only a tender's detail page, not
    # its listing-page context (organisation, tender count, etc. — those
    # are only ever set by the listing/org loop) — a plain overwrite would
    # blank those columns out on every re-check. Blank incoming values now
    # keep whatever's already stored instead of erasing it.
    set_clause = ", ".join(
        f"{c} = COALESCE(NULLIF(EXCLUDED.{c}, ''), scraped_tenders.{c})"
        for c in text_update_columns
    )
    set_clause += ", deadline_at = COALESCE(EXCLUDED.deadline_at, scraped_tenders.deadline_at)"

    sql = f"""
        INSERT INTO scraped_tenders ({", ".join(insert_columns)})
        VALUES {placeholders}
        ON CONFLICT (source_key, tender_id) DO UPDATE SET
            {set_clause},
            updated_at = NOW()
    """

    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, sql, values)
        conn.commit()
        print(f"[DB] [{source['key']}] ✓ Upserted {len(values)} tender(s) into scraped_tenders")
    except Exception:
        conn.rollback()
        raise


def get_soon_to_expire(source: dict, days: int) -> list[dict]:
    """Already-known tenders (already in Neon) from this source whose
    recorded deadline falls within the next `days` — candidates for a
    corrigendum re-check. The normal incremental scrape stops at the first
    already-known tender id it hits (see base_scraper.py), so a deadline
    extension published after the first scrape is otherwise never seen.
    Never raises — if Neon isn't reachable, the caller just skips the
    re-check pass for this run rather than failing the whole scrape."""
    try:
        conn = _get_connection()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT tender_id, tender_detail_url FROM scraped_tenders
                   WHERE source_key = %s
                     AND deadline_at IS NOT NULL
                     AND deadline_at BETWEEN CURRENT_DATE AND CURRENT_DATE + %s * INTERVAL '1 day'
                     AND tender_detail_url IS NOT NULL AND tender_detail_url != ''""",
                (source["key"], days),
            )
            rows = cur.fetchall()
        return [{"tender_id": r[0], "detail_url": r[1]} for r in rows]
    except Exception as e:
        print(f"[DB] [{source.get('key')}] Warning: could not load soon-to-expire tenders – {e}")
        return []
