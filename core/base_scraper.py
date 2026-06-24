"""
core/base_scraper.py

Key changes:
- scrape() writes to sheet after EACH org (not at the end)
- Reads run state (last processed org index) at startup → resumes if previous run was killed
- Saves run state after each org → next run picks up where this one stopped
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional
import os
import re

from selenium.webdriver.remote.webdriver import WebDriver


class BaseScraper(ABC):

    def __init__(self, driver: WebDriver, source: dict):
        self.driver   = driver
        self.source   = source
        self.base_url = source["base_url"]
        self.name     = source["name"]

    # ── shared helpers ───────────────────────────────────────────────────────

    @staticmethod
    def clean_text(text: str) -> str:
        text = text.replace("\xa0", " ").strip()
        text = re.sub(r"\s+", " ", text)
        return text.rstrip(":").strip()

    @staticmethod
    def clean_number(text: str) -> str:
        text = BaseScraper.clean_text(text)
        return re.sub(r"[^\d.]", "", text)

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
        print(f"[{self.name}] Debug HTML → {path}")

    # ── abstract interface ───────────────────────────────────────────────────

    @abstractmethod
    def fetch_org_list(self) -> list[dict]:
        ...

    @abstractmethod
    def fetch_tender_list_incremental(
        self, org_url: str, known_ids: set[str]
    ) -> tuple[list[dict], bool]:
        ...

    @abstractmethod
    def fetch_tender_detail(self, detail_url: str) -> dict:
        ...

    # ── orchestrator entry point ─────────────────────────────────────────────

    def scrape(
        self,
        max_orgs:    Optional[int] = None,
        max_per_org: Optional[int] = None,
    ) -> int:
        """
        Returns total count of new tenders written this run.
        Writes to sheet after every org so nothing is lost if Actions kills the job.
        Resumes from last saved org index if previous run was interrupted.
        """
        from core.config import FIXED_HEADERS
        from output.sheets_writer import (
            get_existing_ids,
            get_run_state,
            save_run_state,
            write_tenders_batch,
        )

        fetch_date  = self.now_iso()
        total_written = 0

        # ── load existing IDs once ───────────────────────────────────────────
        known_ids = get_existing_ids(self.name)

        # ── fetch full org list ──────────────────────────────────────────────
        all_orgs = self.fetch_org_list()
        if max_orgs:
            all_orgs = all_orgs[:max_orgs]

        total_orgs = len(all_orgs)

        # ── resume from last saved position ─────────────────────────────────
        last_index, last_name = get_run_state()

        # if last run completed all orgs, reset and start fresh
        if last_index >= total_orgs:
            print(f"[{self.name}] Full cycle complete — resetting to org 0")
            last_index = 0

        start_index = last_index  # resume from here
        if start_index > 0:
            print(f"[{self.name}] Resuming from org {start_index}/{total_orgs} ('{last_name}')")
        else:
            print(f"[{self.name}] Starting fresh — {total_orgs} organisations")

        # ── main loop ────────────────────────────────────────────────────────
        for i in range(start_index, total_orgs):
            org          = all_orgs[i]
            org_name     = org["org_name"]
            tender_count = org["tender_count"]
            org_url      = org["org_url"]

            try:
                stubs, hit_known = self.fetch_tender_list_incremental(org_url, known_ids)

                if not stubs:
                    status = "up-to-date" if hit_known else "no tenders"
                    print(f"[{self.name}]  [{i+1}/{total_orgs}] {org_name} — {status}")
                else:
                    print(f"[{self.name}]  [{i+1}/{total_orgs}] {org_name} "
                          f"— {len(stubs)} new tender(s)")

                    org_tenders = []
                    fetched = 0
                    for stub in stubs:
                        if max_per_org and fetched >= max_per_org:
                            break
                        try:
                            detail = self.fetch_tender_detail(stub["detail_url"])
                            record = {h: "" for h in FIXED_HEADERS}
                            record.update(detail)
                            record["Organisation"]   = org_name
                            record["Tender Count"]   = tender_count
                            record["Source Website"] = self.name
                            record["Fetch Date"]     = fetch_date
                            if not record.get("Tender ID") and stub.get("tender_id"):
                                record["Tender ID"] = stub["tender_id"]
                            org_tenders.append(record)
                            known_ids.add(stub["tender_id"])
                            fetched += 1
                        except Exception as e:
                            print(f"[{self.name}]   ✗ detail error: {e}")
                            continue

                    # ── WRITE IMMEDIATELY after this org ─────────────────────
                    write_tenders_batch(org_tenders)
                    total_written += len(org_tenders)

            except Exception as e:
                print(f"[{self.name}]  ✗ org error ({org_name}): {e}")
                # still save state so we skip this broken org next time
            
            # ── save progress after every org ────────────────────────────────
            save_run_state(i + 1, org_name, fetch_date)

        print(f"[{self.name}] Run complete — {total_written} new tenders written")
        return total_written
