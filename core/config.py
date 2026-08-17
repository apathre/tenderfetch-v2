"""
core/config.py  –  Central configuration for all sources and output settings.
To add a new source website, just add an entry to SOURCES.
"""

import os

# ── Output / Google Sheets ──────────────────────────────────────────────────
SHEETS_CONFIG_FILE = "sheets.json"
# Each source now writes to its own worksheet tab (see "sheet_tab" in SOURCES
# below) so portals don't share one growing "database". RunState also keys
# its rows by source "key", so sources no longer stomp each other's resume
# position when run in parallel.

# ── Scraping limits (set to None for unlimited) ─────────────────────────────
MAX_ORGANIZATIONS_TO_PROCESS = None
MAX_TENDERS_PER_ORG          = None

# After the normal discovery pass, re-fetch the detail page for already-known
# tenders whose recorded deadline falls within this many days — catches
# corrigendum-driven deadline extensions that the discovery pass alone would
# never see (it stops at the first already-known tender id it hits). Set to
# 0 to disable.
RECHECK_DEADLINE_WINDOW_DAYS = 7

# ── Concurrency ─────────────────────────────────────────────────────────────
MAX_CONCURRENT_DRIVERS = 2   # how many Chrome instances to run in parallel

# ── Google API scopes ────────────────────────────────────────────────────────
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ── Canonical output columns ────────────────────────────────────────────────
# "Fetch Date" and "Source Website" are always appended automatically.
FIXED_HEADERS = [
    "Source Website",
    "Fetch Date",
    "Organisation",
    "Tender Count",
    "Organization Chain",
    "Tender Reference Number",
    "Tender ID",
    "Tender Type",
    "Tender Category",
    "Form of Contract",
    "Tender Fee in Rs",
    "Tender Fee Exemption Allowed",
    "EMD Amount in Rs",
    "EMD Exemption Allowed",
    "EMD Fee Type",
    "Title",
    "Work Description",
    "NDA/Pre Qualification",
    "Tender Value in Rs",
    "Contract Type",
    "Location",
    "Product Category",
    "Sub Category",
    "Bid Validity(Days)",
    "Period of Work(Days)",
    "Pre Bid Meeting Place",
    "Pre Bid Meeting Address",
    "Pre Bid Meeting Date",
    "Bid Opening Place",
    "Published Date",
    "Bid Opening Date",
    "Document Download / Sale Start Date",
    "Document Download / Sale End Date",
    "Clarification Start Date",
    "Clarification End Date",
    "Bid Submission Start Date",
    "Bid Submission End Date",
    "Tender Inviting Authority Name",
    "Tender Inviting Authority Address",
    "Tender Detail URL",
]

NUMERIC_FIELDS = {"Tender Fee in Rs", "EMD Amount in Rs", "Tender Value in Rs"}

# ── Source definitions ───────────────────────────────────────────────────────
# Each entry tells the scraper:
#   key          – short stable id, used as the RunState row key (no spaces)
#   name         – human-readable label stored in "Source Website" column
#   base_url     – root URL of the portal
#   scraper      – dotted import path of the scraper class inside scrapers/
#   sheet_tab    – worksheet tab this source writes to (its own "database")
#   enabled      – easy on/off toggle
#
# Portals sharing the NIC eProcure template (eprocure.gov.in, mptenders,
# state GePNIC clones) all use the same CPPPScraper – just point base_url.

SOURCES = [
    {
        "key":      "CPPP",
        "name":     "CPPP / eProcure (Central)",
        "base_url": "https://eprocure.gov.in/eprocure/app",
        "scraper":  "scrapers.cppp_scraper.CPPPScraper",
        "sheet_tab": "TendersData",   # existing tab with 12,000+ already-scraped rows — keep as-is, do NOT rename to TendersData_CPPP
        "enabled":  True,
    },
    {
        "key":      "MP",
        "name":     "MP Tenders",
        "base_url": "https://mptenders.gov.in/nicgep/app",
        "scraper":  "scrapers.cppp_scraper.CPPPScraper",   # same template
        "sheet_tab": "TendersData_MP",
        "enabled":  False,   # flip to True once you want to activate
    },
    {
        "key":      "GeM",
        "name":     "GeMportal",
        "base_url": "https://bidplus.gem.gov.in",
        "scraper":  "scrapers.gem_scraper.GeMScraper",
        "sheet_tab": "TendersData_GeM",
        "enabled":  False,
    },
    {
        "key":      "UP",
        "name":     "UP Tenders",
        "base_url": "https://etender.up.nic.in/nicgep/app",
        "scraper":  "scrapers.cppp_scraper.CPPPScraper",
        "sheet_tab": "TendersData_UP",
        "enabled":  False,
    },
    {
        "key":      "Rajasthan",
        "name":     "Rajasthan Tenders",
        "base_url": "https://eproc.rajasthan.gov.in/nicgep/app",
        "scraper":  "scrapers.cppp_scraper.CPPPScraper",
        "sheet_tab": "TendersData_Rajasthan",
        "enabled":  False,
    },
    {
        "key":      "TN",
        "name":     "Tamil Nadu Tenders",
        "base_url": "https://tntenders.gov.in/nicgep/app",
        "scraper":  "scrapers.cppp_scraper.CPPPScraper",
        "sheet_tab": "TendersData_TN",
        "enabled":  False,
    },
    {
        "key":      "Kerala",
        "name":     "Kerala Tenders",
        "base_url": "https://etenders.kerala.gov.in/nicgep/app",
        "scraper":  "scrapers.cppp_scraper.CPPPScraper",
        "sheet_tab": "TendersData_Kerala",
        "enabled":  False,
    },
    {
        "key":      "Maharashtra",
        "name":     "Maharashtra Tenders",
        "base_url": "https://mahatenders.gov.in/nicgep/app",
        "scraper":  "scrapers.cppp_scraper.CPPPScraper",
        "sheet_tab": "TendersData_Maharashtra",
        "enabled":  False,
    },
    # ── Add more NIC/GePNIC state portals here ───────────────────────────────
    # {
    #     "key":      "Punjab",
    #     "name":     "Punjab Tenders",
    #     "base_url": "https://etenders.punjab.gov.in/nicgep/app",
    #     "scraper":  "scrapers.cppp_scraper.CPPPScraper",
    #     "sheet_tab": "TendersData_Punjab",
    #     "enabled":  False,
    # },
    {
        "key":      "NTPC",
        "name":     "NTPC eProcurement",
        "base_url": "https://eprocurentpc.nic.in/nicgep/app",
        "scraper":  "scrapers.cppp_scraper.CPPPScraper",   # same NIC/GePNIC template as CPPP
        "sheet_tab": "TendersData_NTPC",
        "enabled":  False,   # flip to True once verified
    },
    {
        "key":      "SECI",
        "name":     "Solar Energy Corporation of India (SECI)",
        "base_url": "https://www.seci.co.in",
        "scraper":  "scrapers.seci_scraper.SECIScraper",
        "sheet_tab": "TendersData_SECI",
        "enabled":  False,
    },
    {
        "key":      "SJVN",
        "name":     "SJVN Limited",
        "base_url": "https://sjvn.nic.in",
        "scraper":  "scrapers.sjvn_scraper.SJVNScraper",
        "sheet_tab": "TendersData_SJVN",
        "enabled":  False,
    },
    # PowerGrid (apps.powergrid.in) intentionally not added yet — 8,405+
    # tenders with no natural org grouping means it needs its own chunking
    # strategy (multiple pseudo-orgs, e.g. one per listing page) so the
    # existing per-org resume/write cadence doesn't lose an entire run's
    # progress to a GitHub Actions timeout. Follow-up, not part of this batch.
]
