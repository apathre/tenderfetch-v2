"""
core/base_scraper.py  –  Abstract base every source scraper must implement.

Each concrete scraper only needs to implement:
    fetch_org_list()    → list[dict]  (org_name, tender_count, org_url)
    fetch_tender_list() → list[dict]  (title, detail_url)
    fetch_tender_detail() → dict      (all canonical fields)

The orchestrator (main.py) handles:
    • driver lifecycle
    • concurrency
    • rate-limit / CAPTCHA logging
    • dedup & sheet writing
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional
import os
import re

from selenium.webdriver.remote.webdriver import WebDriver


class BaseScraper(ABC):
    """
    All scraper subclasses receive a live driver and a source config dict.
    They must NOT manage driver lifecycle themselves.
    """

    def __init__(self, driver: WebDriver, source: dict):
        self.driver  = driver
        self.source  = source           # from config.SOURCES
        self.base_url = source["base_url"]
        self.name     = source["name"]

    # ── helpers available to all scrapers ───────────────────────────────────

    @staticmethod
    def clean_text(text: str) -> str:
        text = text.replace("\xa0", " ").strip()
        text = re.sub(r"\s+", " ", text)
        return text.rstrip(":").strip()

    @staticmethod
    def clean_number(text: str) -> str:
        text = BaseScraper.clean_text(text)
        text = re.sub(r"[^\d.]", "", text)
        return text

    def now_iso(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def page_has_captcha(self) -> bool:
        try:
            body = self.driver.find_element("tag name", "body").text.lower()
            indicators = ["captcha", "verify", "robot", "recaptcha",
                          "not a robot", "enter the code", "security check"]
            found = any(w in body for w in indicators)
            if found:
                print(f"[{self.name}] ⚠  CAPTCHA detected – continuing")
            return found
        except Exception:
            return False

    def save_debug_html(self, filename: str) -> None:
        path = os.path.join(os.getcwd(), filename)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.driver.page_source)
        print(f"[{self.name}] Debug HTML saved → {path}")

    # ── abstract interface ───────────────────────────────────────────────────

    @abstractmethod
    def fetch_org_list(self) -> list[dict]:
        """
        Navigate to the organisations listing page.
        Return: [{"org_name": str, "tender_count": str, "org_url": str}, ...]
        """
        ...

    @abstractmethod
    def fetch_tender_list(self, org_url: str) -> list[dict]:
        """
        Navigate to one org's tender listing, handling pagination.
        Return: [{"title": str, "detail_url": str}, ...]
        """
        ...

    @abstractmethod
    def fetch_tender_detail(self, detail_url: str) -> dict:
        """
        Navigate to a single tender detail page.
        Return a dict keyed by FIXED_HEADERS field names.
        """
        ...

    # ── public entry point called by the orchestrator ────────────────────────

    def scrape(
        self,
        max_orgs:   Optional[int] = None,
        max_per_org: Optional[int] = None,
    ) -> list[dict]:
        """
        Orchestrate fetch_org_list → fetch_tender_list → fetch_tender_detail
        and attach metadata (Source Website, Fetch Date) to every record.
        """
        from core.config import FIXED_HEADERS  # avoid circular at module level

        fetch_date = self.now_iso()
        all_tenders: list[dict] = []

        orgs = self.fetch_org_list()
        if max_orgs:
            orgs = orgs[:max_orgs]

        print(f"[{self.name}] {len(orgs)} organisations to process")

        for org in orgs:
            org_name     = org["org_name"]
            tender_count = org["tender_count"]
            org_url      = org["org_url"]
            print(f"[{self.name}]  → {org_name}  ({tender_count})")

            try:
                tender_stubs = self.fetch_tender_list(org_url)
                if max_per_org:
                    tender_stubs = tender_stubs[:max_per_org]

                for stub in tender_stubs:
                    try:
                        detail = self.fetch_tender_detail(stub["detail_url"])
                        record = {h: "" for h in FIXED_HEADERS}
                        record.update(detail)
                        record["Organisation"]   = org_name
                        record["Tender Count"]   = tender_count
                        record["Source Website"] = self.name
                        record["Fetch Date"]     = fetch_date
                        all_tenders.append(record)
                    except Exception as e:
                        print(f"[{self.name}]   ✗ detail error: {e}")
                        continue

            except Exception as e:
                print(f"[{self.name}]  ✗ org error ({org_name}): {e}")
                continue

        print(f"[{self.name}] Collected {len(all_tenders)} tenders")
        return all_tenders
