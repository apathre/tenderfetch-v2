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
│   ├── workflows/prune_sheets.yml    # weekly – trims expired rows from every Sheet tab
│   └── scripts/resolve_sources.py    # picks which source key(s) run per trigger
│
├── core/
│   ├── config.py             # SOURCES list, FIXED_HEADERS, limits – edit here
│   ├── driver.py             # Chrome driver factory (shared)
│   └── base_scraper.py       # Abstract base class all scrapers inherit
│
├── scrapers/
│   ├── cppp_scraper.py       # NIC eProcure template (CPPP, MP Tenders, state GePNIC, NTPC)
│   ├── gem_scraper.py        # GeM portal stub (implement when needed)
│   ├── seci_scraper.py       # SECI (seci.co.in) — own site, single org, DataTables.js listing
│   └── sjvn_scraper.py       # SJVN (sjvn.nic.in) — own Drupal site, single org, ?page=N pagination
│
├── database/
│   └── scraped_tenders.sql   # DDL for the Neon mirror (run once, see below)
│
├── scripts/
│   ├── backfill_sheet_to_db.py     # one-time: copy existing Sheet rows into Neon
│   └── prune_expired_sheet_rows.py # scheduled: drop old rows + shrink each tab's grid
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

The DB write happens right after the Sheets write in `core/base_scraper.py`.
Both directions are fault-isolated — a Neon outage (or a missing
`DISCOVERY_DATABASE_URL`) never blocks the Sheets write, and a Sheets
failure (e.g. the shared workbook hitting Google's 10M-cell-per-spreadsheet
limit — see "Sheets capacity" below) never blocks the Neon write. Sheets is
a best-effort mirror; Neon is the real source of truth.

## Corrigendum re-checks (`RECHECK_DEADLINE_WINDOW_DAYS`)

The normal discovery pass stops at the first *already-known* tender id it
hits on each run (an efficiency trade-off — avoids re-fetching the entire
backlog every time). That means once a tender's scraped, its deadline is
never re-verified — a corrigendum extending it, published after the first
scrape, is otherwise never seen.

After the org loop, `core/base_scraper.py` queries Neon for already-known
tenders from this source whose recorded deadline falls within
`RECHECK_DEADLINE_WINDOW_DAYS` (default 7) and re-fetches just those detail
pages, upserting any changes. This is Neon-only — Sheets' writer only
appends, so writing re-checks there would create duplicate rows instead of
updating the existing one. Set the constant to `0` in `core/config.py` to
disable.

## Sheets capacity (`SHEETS_PRUNE_GRACE_DAYS`)

Google enforces a 10-million-cell limit **per spreadsheet**, shared across
every tab. Since Sheets is append-only, the workbook only ever grows —
this limit has already been hit once (`Invalid requests[0].addSheet: ...
above the limit of 10000000 cells`), which blocked *every* new tab
creation, not just the one that triggered it.

`scripts/prune_expired_sheet_rows.py`, run weekly via
`.github/workflows/prune_sheets.yml`, deletes rows whose "Bid Submission
End Date" is more than `SHEETS_PRUNE_GRACE_DAYS` (default 30) in the past,
**and shrinks each tab's reserved grid down to what it actually needs** —
clearing cell values alone doesn't free budget, Google's limit is on grid
dimensions (rows × cols), not how many cells hold data, and
`_get_worksheet()`'s `add_worksheet(rows=10000, ...)` reserves that many
rows the moment any new tab is created regardless of how few ever get
filled. A row with no parseable deadline is always kept — never delete
data pruning can't confidently judge as expired.

Neon is untouched by this — no comparable capacity constraint at this
scale, and it's the permanent record Discovery reads from regardless of
what happens to the Sheets mirror.

## sheets.json format

`sheets.json` is **not committed** (it's in `.gitignore`) since it names your
actual spreadsheet — the workflow reconstructs it at runtime from the
`SHEET_URL` secret above. For local runs, create it yourself in the repo root:

```json
{ "SHEET_URL": "https://docs.google.com/spreadsheets/d/YOUR_ID/edit" }
```
