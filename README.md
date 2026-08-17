# tenderDataFetch v2

Multi-source tender scraper for Indian government procurement portals.

## Project structure

```
tenderDataFetch_v2/
├── main.py                   # Orchestrator – runs enabled sources, or one if SOURCE_KEY is set
├── requirements.txt
├── sheets.json               # { "SHEET_URL": "https://docs.google.com/..." }
│
├── .github/
│   ├── workflows/fetch_tenders.yml   # matrix workflow – one job per source
│   └── scripts/resolve_sources.py    # picks which source key(s) run per trigger
│
├── core/
│   ├── config.py             # SOURCES list, FIXED_HEADERS, limits – edit here
│   ├── driver.py             # Chrome driver factory (shared)
│   └── base_scraper.py       # Abstract base class all scrapers inherit
│
├── scrapers/
│   ├── cppp_scraper.py       # NIC eProcure template (CPPP, MP Tenders, state GePNIC)
│   └── gem_scraper.py        # GeM portal stub (implement when needed)
│
├── database/
│   └── scraped_tenders.sql   # DDL for the Neon mirror (run once, see below)
│
├── scripts/
│   └── backfill_sheet_to_db.py  # one-time: copy existing Sheet rows into Neon
│
└── output/
    ├── sheets_writer.py      # Google Sheets writer – one worksheet tab per source
    └── db_writer.py          # Neon Postgres writer – mirrors every write into scraped_tenders
```

## Each source has its own worksheet tab

Every entry in `core/config.py` writes to its own tab (`sheet_tab`), and has
its own row in the shared `RunState` tab (keyed by `key`) tracking resume
progress. Sources never share a tab or a resume position, so running several
at once can't corrupt each other's data.

Two columns are also always populated on every row:

| Column | Value |
|---|---|
| `Source Website` | Human-readable portal name from `config.SOURCES` |
| `Fetch Date` | UTC timestamp when the run executed |

## How the workflow decides which source(s) to run

`fetch_tenders.yml` runs a `resolve` job first (`resolve_sources.py`), then a
`scrape` job with one **matrix** entry per resolved source key — each gets
its own runner, own Chrome, own full 60-minute timeout, so one source's slow
initial backfill never steals time from another source's ongoing runs.

- **Manual run** (`workflow_dispatch`): pick a specific source from the
  dropdown to run just that one (works even if it's `enabled: False` — handy
  for testing a new state before switching it on for the schedule), or pick
  `all` to run every currently `enabled: True` source.
- **Scheduled run**: each `cron:` entry maps to one source via `CRON_TO_KEY`
  in `resolve_sources.py` — keep that map in sync with the cron list. A
  scheduled source only runs if it's still `enabled: True`.

## How to add a new NIC/GePNIC state portal

These portals (mptenders.gov.in, Rajasthan SPPP, UP Tenders, etc.) share the
same HTML template as CPPP. Add an entry in `core/config.py`:

```python
SOURCES = [
    ...
    {
        "key":       "Rajasthan",
        "name":      "Rajasthan Tenders",
        "base_url":  "https://eproc.rajasthan.gov.in/nicgep/app",
        "scraper":   "scrapers.cppp_scraper.CPPPScraper",
        "sheet_tab": "TendersData_Rajasthan",
        "enabled":   True,
    },
]
```

If you want it on its own schedule, add a `cron:` entry to
`.github/workflows/fetch_tenders.yml` and a matching line in `CRON_TO_KEY`
in `.github/scripts/resolve_sources.py`. Otherwise trigger it manually via
`workflow_dispatch` by picking its `key` from the dropdown.

## How to add a structurally different portal (e.g. GeM, IREPS)

1. Create `scrapers/my_scraper.py`
2. Subclass `BaseScraper` and implement the three methods:
   - `fetch_org_list() → list[dict]`
   - `fetch_tender_list(org_url) → list[dict]`
   - `fetch_tender_detail(detail_url) → dict`
3. Add an entry to `SOURCES` pointing `"scraper"` to your new class.

## Speed levers

| Setting (core/config.py) | Default | Effect |
|---|---|---|
| `MAX_CONCURRENT_DRIVERS` | 2 | Chrome instances running in parallel |
| `MAX_ORGANIZATIONS_TO_PROCESS` | 5 | Per source; `None` = unlimited |
| `MAX_TENDERS_PER_ORG` | 10 | Per org; `None` = unlimited |
| `T_*` constants in cppp_scraper.py | 4–6 s | Per-page sleep; reduce with caution |

## Environment variables / GitHub secrets

| Secret | Required | Description |
|---|---|---|
| `SERVICE_ACCOUNT_JSON` | Yes | Full JSON content of GCP service account key |
| `SHEET_URL` | Yes | Your Google Sheet's URL (the workflow writes this into `sheets.json` at runtime — see below) |
| `DISCOVERY_DATABASE_URL` | Yes | Connection string for the **dedicated** Neon project that mirrors scraped tenders (`postgresql://user:pass@host/db?sslmode=require`). This is intentionally a **separate Neon project** from TenderDesk's production app database — this workflow should never hold credentials that can reach user/billing data. |

Add these under repo **Settings → Secrets and variables → Actions → New repository secret**.

## Neon mirror (`scraped_tenders`)

Every scraped tender is written both to its Google Sheet tab (unchanged) and,
via `output/db_writer.py`, upserted into a `scraped_tenders` table in a
separate Neon Postgres project — that's what TenderDesk's Discovery feature
reads from, since a spreadsheet can't be filtered/paginated/indexed the way
a growing tender feed needs.

Setup (one time):
1. Create a new free Neon project (e.g. `tenderfetch-discovery`).
2. Run `database/scraped_tenders.sql` against it (Neon SQL editor, or `psql "$DISCOVERY_DATABASE_URL" -f database/scraped_tenders.sql`).
3. Add its connection string as the `DISCOVERY_DATABASE_URL` secret above.
4. Optionally run `scripts/backfill_sheet_to_db.py` once locally to copy the
   existing `TendersData` tab's rows into the new table (see the script's
   docstring for required local env vars).

The DB write happens right after the Sheets write in `core/base_scraper.py`,
wrapped in its own try/except — a Neon outage or a missing
`DISCOVERY_DATABASE_URL` never blocks or breaks the Sheets write.

## sheets.json format

`sheets.json` is **not committed** (it's in `.gitignore`) since it names your
actual spreadsheet — the workflow reconstructs it at runtime from the
`SHEET_URL` secret above. For local runs, create it yourself in the repo root:

```json
{ "SHEET_URL": "https://docs.google.com/spreadsheets/d/YOUR_ID/edit" }
```
