-- database/scraped_tenders.sql
--
-- Run this once against the dedicated "tenderfetch-discovery" Neon project
-- (NOT tenderdesk-backend's production database — see README).
--
-- One row per (source_key, tender_id): output/db_writer.py upserts on that
-- pair, so a re-scraped tender (e.g. after a corrigendum) refreshes the row
-- instead of erroring or duplicating.

CREATE TABLE IF NOT EXISTS scraped_tenders (
  id                                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- identity / provenance
  source_key                          TEXT NOT NULL,   -- core.config.SOURCES[].key, e.g. "CPPP"
  source_website                      TEXT,
  fetch_date                          TEXT,             -- raw "YYYY-MM-DD HH:MM UTC" from the scraper
  tender_id                           TEXT NOT NULL,
  tender_detail_url                   TEXT,

  -- organisation
  organisation                        TEXT,
  organization_chain                  TEXT,
  tender_count                        TEXT,

  -- classification
  tender_reference_number             TEXT,
  tender_type                         TEXT,
  tender_category                     TEXT,
  form_of_contract                    TEXT,
  contract_type                       TEXT,
  product_category                    TEXT,
  sub_category                        TEXT,

  -- fees / value — kept as raw text (same as the sheet); cast at query time if ever needed
  tender_fee_in_rs                    TEXT,
  tender_fee_exemption_allowed        TEXT,
  emd_amount_in_rs                    TEXT,
  emd_exemption_allowed               TEXT,
  emd_fee_type                        TEXT,
  tender_value_in_rs                  TEXT,

  -- description
  title                                TEXT,
  work_description                     TEXT,
  nda_pre_qualification                TEXT,
  location                             TEXT,
  bid_validity_days                    TEXT,
  period_of_work_days                  TEXT,

  -- dates — raw text, portal formats aren't consistent enough to trust a strict DATE column
  published_date                       TEXT,
  pre_bid_meeting_place                TEXT,
  pre_bid_meeting_address              TEXT,
  pre_bid_meeting_date                 TEXT,
  bid_opening_place                    TEXT,
  bid_opening_date                     TEXT,
  document_download_sale_start_date    TEXT,
  document_download_sale_end_date      TEXT,
  clarification_start_date             TEXT,
  clarification_end_date               TEXT,
  bid_submission_start_date            TEXT,
  bid_submission_end_date              TEXT,

  -- best-effort parse of bid_submission_end_date, nullable on parse failure.
  -- Powers Discovery's "closing soon" sort/filter without ever blocking a write.
  deadline_at                          DATE,

  -- authority
  tender_inviting_authority_name       TEXT,
  tender_inviting_authority_address    TEXT,

  created_at                           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at                           TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT scraped_tenders_source_tender_uniq UNIQUE (source_key, tender_id)
);

CREATE INDEX IF NOT EXISTS idx_scraped_tenders_deadline     ON scraped_tenders (deadline_at);
CREATE INDEX IF NOT EXISTS idx_scraped_tenders_location     ON scraped_tenders (location);
CREATE INDEX IF NOT EXISTS idx_scraped_tenders_type         ON scraped_tenders (tender_type);
CREATE INDEX IF NOT EXISTS idx_scraped_tenders_organisation ON scraped_tenders (organisation);
CREATE INDEX IF NOT EXISTS idx_scraped_tenders_source_key   ON scraped_tenders (source_key);

-- keep updated_at current on every upsert
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_scraped_tenders_updated_at ON scraped_tenders;
CREATE TRIGGER trg_scraped_tenders_updated_at
  BEFORE UPDATE ON scraped_tenders
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
