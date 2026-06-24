"""
core/config.py  –  Central configuration for all sources and output settings.
To add a new source website, just add an entry to SOURCES.
"""

import os

# ── Output / Google Sheets ──────────────────────────────────────────────────
SHEETS_CONFIG_FILE = "sheets.json"
WORKSHEET_NAME     = "TendersData"

# ── Scraping limits (set to None for unlimited) ─────────────────────────────
MAX_ORGANIZATIONS_TO_PROCESS = 5
MAX_TENDERS_PER_ORG          = 10

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
#   name         – human-readable label stored in "Source Website" column
#   base_url     – root URL of the portal
#   scraper      – dotted import path of the scraper class inside scrapers/
#   enabled      – easy on/off toggle
#
# Portals sharing the NIC eProcure template (eprocure.gov.in, mptenders,
# state GePNIC clones) all use the same CPPPScraper – just point base_url.

SOURCES = [
    {
        "name":    "CPPP / eProcure (Central)",
        "base_url": "https://eprocure.gov.in/eprocure/app",
        "scraper": "scrapers.cppp_scraper.CPPPScraper",
        "enabled": True,
    },
    {
        "name":    "MP Tenders",
        "base_url": "https://mptenders.gov.in/nicgep/app",
        "scraper": "scrapers.cppp_scraper.CPPPScraper",   # same template
        "enabled": False,   # flip to True once you want to activate
    },
    {
        "name":    "GeMportal",
        "base_url": "https://bidplus.gem.gov.in",
        "scraper": "scrapers.gem_scraper.GeMScraper",
        "enabled": False,
    },
    # ── Add more NIC/GePNIC state portals here ───────────────────────────────
    # {
    #     "name":    "Rajasthan Tenders",
    #     "base_url": "https://sppp.rajasthan.gov.in/nicgep/app",
    #     "scraper": "scrapers.cppp_scraper.CPPPScraper",
    #     "enabled": False,
    # },
]
