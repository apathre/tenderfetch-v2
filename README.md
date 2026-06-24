# tenderDataFetch v2

Multi-source tender scraper for Indian government procurement portals.

## Project structure

```
tenderDataFetch_v2/
├── main.py                   # Orchestrator – runs all enabled sources in parallel
├── requirements.txt
├── sheets.json               # { "SHEET_URL": "https://docs.google.com/..." }
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
└── output/
    └── sheets_writer.py      # Google Sheets writer with dedup
```

## Columns added in v2

Two columns are now always populated:

| Column | Value |
|---|---|
| `Source Website` | Human-readable portal name from `config.SOURCES` |
| `Fetch Date` | UTC timestamp when the run executed |

## How to add a new NIC/GePNIC state portal

These portals (mptenders.gov.in, Rajasthan SPPP, UP Tenders, etc.) share the
same HTML template as CPPP.  No code changes needed — just add an entry in
`core/config.py`:

```python
SOURCES = [
    ...
    {
        "name":    "Rajasthan Tenders",
        "base_url": "https://sppp.rajasthan.gov.in/nicgep/app",
        "scraper": "scrapers.cppp_scraper.CPPPScraper",
        "enabled": True,
    },
]
```

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

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `SERVICE_ACCOUNT_JSON` | Yes | Full JSON content of GCP service account key |

## sheets.json format

```json
{ "SHEET_URL": "https://docs.google.com/spreadsheets/d/YOUR_ID/edit" }
```
