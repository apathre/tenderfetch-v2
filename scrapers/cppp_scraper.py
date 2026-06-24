"""
scrapers/cppp_scraper.py
Handles:  CPPP (eprocure.gov.in) and any NIC/GePNIC state-portal clone
          that shares the same HTML structure (mptenders.gov.in, etc.)

To activate a new NIC portal, add an entry to config.SOURCES with:
    "scraper": "scrapers.cppp_scraper.CPPPScraper"
    "base_url": "<portal base URL>"
No code changes needed.
"""

import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By

from core.base_scraper import BaseScraper
from core.config import FIXED_HEADERS, NUMERIC_FIELDS


# ── page timing constants (seconds) ─────────────────────────────────────────
T_ORG_LIST    = 6   # wait after loading org-list page
T_ORG_PAGE    = 4   # wait after loading an org's tender list
T_DETAIL      = 4   # wait after loading a detail page
T_BACK        = 2   # wait after driver.back()
T_NEXT_PAGE   = 4   # wait after clicking Next


class CPPPScraper(BaseScraper):
    """Scraper for the NIC eProcure / CPPP template portals."""

    # ── fetch_org_list ───────────────────────────────────────────────────────

    def fetch_org_list(self) -> list[dict]:
        url = self.base_url + "?page=FrontEndTendersByOrganisation&service=page"
        print(f"[{self.name}] Loading org list → {url}")
        self.driver.get(url)
        time.sleep(T_ORG_LIST)
        self.page_has_captcha()

        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        rows = soup.find_all("tr", attrs={"id": lambda x: x and "informal" in x.lower()})

        if len(rows) < 3:
            rows = [
                tr for tr in soup.select("table tr")
                if len(tr.find_all("td")) >= 3 and tr.find_all("td")[1].get_text(strip=True)
            ]

        orgs = []
        for row in rows:
            tds = row.find_all("td")
            if len(tds) < 3:
                continue
            org_name     = tds[1].get_text(strip=True)
            count_cell   = tds[2]
            tender_count = count_cell.get_text(strip=True)
            link_tag     = count_cell.find("a", href=True)
            if not link_tag:
                continue
            org_url = urljoin(self.base_url, link_tag["href"])
            orgs.append({"org_name": org_name, "tender_count": tender_count, "org_url": org_url})

        return orgs

    # ── fetch_tender_list ────────────────────────────────────────────────────

    def fetch_tender_list(self, org_url: str) -> list[dict]:
        self.driver.get(org_url)
        time.sleep(T_ORG_PAGE)
        self.page_has_captcha()

        stubs: list[dict] = []

        while True:
            soup = BeautifulSoup(self.driver.page_source, "html.parser")
            rows = soup.find_all("tr", attrs={"id": lambda x: x and "informal" in x.lower()})

            if len(rows) < 3:
                rows = [
                    tr for tr in soup.select("table tr")
                    if len(tr.find_all("td")) >= 6 and tr.find_all("td")[4].find("a")
                ]

            for tr in rows:
                cells = tr.find_all("td")
                if len(cells) < 6:
                    continue
                title_cell  = cells[4]
                title       = title_cell.get_text(strip=True)
                detail_link = title_cell.find("a")
                if not detail_link:
                    continue
                href = detail_link["href"]
                if "service=direct" not in href:
                    continue
                detail_url = urljoin(self.base_url, href)
                stubs.append({"title": title, "detail_url": detail_url})

            # pagination
            try:
                next_btn = self.driver.find_element(
                    By.XPATH,
                    "//a[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
                    "'abcdefghijklmnopqrstuvwxyz'),'next')]",
                )
                cls = next_btn.get_attribute("class") or ""
                if "disabled" in cls or not next_btn.is_enabled():
                    break
                next_btn.click()
                time.sleep(T_NEXT_PAGE)
            except Exception:
                break

        return stubs

    # ── fetch_tender_detail ──────────────────────────────────────────────────

    def fetch_tender_detail(self, detail_url: str) -> dict:
        self.driver.get(detail_url)
        time.sleep(T_DETAIL)
        self.page_has_captcha()

        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        data: dict[str, str] = {h: "" for h in FIXED_HEADERS}
        data["Tender Detail URL"] = detail_url

        ct = self.clean_text
        cn = self.clean_number

        # ── generic table parser (td_caption / td_field) ────────────────────
        for table in soup.find_all("table", class_="tablebg"):
            for tr in table.find_all("tr"):
                tds = tr.find_all("td")
                i = 0
                while i < len(tds):
                    cell = tds[i]
                    if "td_caption" in cell.get("class", []):
                        caption = ct(cell.get_text())
                        val = ""
                        if i + 1 < len(tds) and "td_field" in tds[i + 1].get("class", []):
                            val = ct(tds[i + 1].get_text())
                            i += 1
                        self._map_caption(data, caption, val, cn)
                    i += 1

        # ── Work Item Details section ────────────────────────────────────────
        self._parse_section(soup, "Work Item Details", data, cn, {
            "Title":               "Title",
            "Work Description":    "Work Description",
            "NDA/Pre Qualification": "NDA/Pre Qualification",
            "Tender Value":        ("Tender Value in Rs", "number"),
            "Product Category":    "Product Category",
            "Sub category":        "Sub Category",
            "Bid Validity":        "Bid Validity(Days)",
            "Period Of Work":      "Period of Work(Days)",
            "Location":            "Location",
            "Pre Bid Meeting Place":   "Pre Bid Meeting Place",
            "Pre Bid Meeting Address": "Pre Bid Meeting Address",
            "Pre Bid Meeting Date":    "Pre Bid Meeting Date",
            "Bid Opening Place":       "Bid Opening Place",
        })

        # ── Critical Dates section ───────────────────────────────────────────
        self._parse_section(soup, "Critical Dates", data, cn, {
            "Published Date":                    "Published Date",
            "Bid Opening Date":                  "Bid Opening Date",
            "Document Download / Sale Start Date": "Document Download / Sale Start Date",
            "Document Download / Sale End Date":   "Document Download / Sale End Date",
            "Clarification Start Date":            "Clarification Start Date",
            "Clarification End Date":              "Clarification End Date",
            "Bid Submission Start Date":           "Bid Submission Start Date",
            "Bid Submission End Date":             "Bid Submission End Date",
        })

        # ── Tender Inviting Authority section ────────────────────────────────
        self._parse_section(soup, "Tender Inviting Authority", data, cn, {
            "Name":    "Tender Inviting Authority Name",
            "Address": "Tender Inviting Authority Address",
        })

        filled = sum(1 for v in data.values() if v)
        print(f"[{self.name}]   extracted {filled}/{len(FIXED_HEADERS)} fields  ← {detail_url[-60:]}")
        return data

    # ── private helpers ──────────────────────────────────────────────────────

    def _map_caption(self, data, caption, val, cn):
        """Map a generic td_caption/td_field pair to a FIXED_HEADER key."""
        cap_lower = caption.lower()

        # direct overrides first
        if "organisation chain" in cap_lower:
            data["Organization Chain"] = val; return
        if "tender reference number" in cap_lower:
            data["Tender Reference Number"] = val; return
        if "tender id" in cap_lower:
            data["Tender ID"] = val; return

        # fuzzy match against headers
        for header in FIXED_HEADERS[4:]:   # skip metadata cols
            h_lower = (
                header.lower()
                .replace(" in rs", "")
                .replace("(days)", "")
                .strip()
            )
            if h_lower in cap_lower or cap_lower in h_lower:
                data[header] = cn(val) if header in NUMERIC_FIELDS else val
                return

    def _parse_section(self, soup, section_label: str, data: dict, cn, mapping: dict):
        """
        Find a named section table and apply a key→header mapping.
        mapping values can be a string (header name) or ("header", "number").
        """
        anchor = soup.find(string=lambda s: s and section_label in s)
        if not anchor:
            return
        table = anchor.find_parent("table")
        if not table:
            return

        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            raw_key = self.clean_text(tds[0].get_text())
            val     = self.clean_text(" ".join(td.get_text() for td in tds[1:]))

            for map_key, target in mapping.items():
                if map_key.lower() in raw_key.lower():
                    if isinstance(target, tuple):
                        header, mode = target
                        data[header] = cn(val) if mode == "number" else val
                    else:
                        data[target] = val
                    break
