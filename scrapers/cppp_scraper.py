"""
scrapers/cppp_scraper.py
Handles CPPP (eprocure.gov.in) and any NIC/GePNIC state-portal clone.

Key change: fetch_tender_list_incremental() extracts Tender ID directly
from the listing row (last [bracketed] value in the Title cell) and stops
pagination as soon as a known ID is encountered — no wasted detail page loads.
"""

import re
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By

from core.base_scraper import BaseScraper
from core.config import FIXED_HEADERS, NUMERIC_FIELDS

# ── page timing (seconds) ────────────────────────────────────────────────────
T_ORG_LIST  = 6
T_ORG_PAGE  = 4
T_DETAIL    = 4
T_NEXT_PAGE = 4

# Tender ID pattern: YYYY_ORGCODE_NUMBER_VERSION  e.g. 2026_DDA_914625_1
_TENDER_ID_RE = re.compile(r'\d{4}_[A-Z0-9]+_\d+_\d+')


def _extract_tender_id(cell_text: str) -> str:
    """Extract Tender ID from the Title+Ref cell on the listing page."""
    matches = _TENDER_ID_RE.findall(cell_text)
    return matches[-1] if matches else ""


class CPPPScraper(BaseScraper):

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
                if len(tr.find_all("td")) >= 3
                and tr.find_all("td")[1].get_text(strip=True)
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

        print(f"[{self.name}] Found {len(orgs)} organisations")
        return orgs

    # ── fetch_tender_list_incremental ────────────────────────────────────────

    def fetch_tender_list_incremental(
        self, org_url: str, known_ids: set[str]
    ) -> tuple[list[dict], bool]:
        """
        Paginate through tender list, stopping as soon as a known Tender ID
        is encountered. Tenders are listed newest-first so this is safe.

        Returns (new_stubs, hit_known_id).
        """
        self.driver.get(org_url)
        time.sleep(T_ORG_PAGE)
        self.page_has_captcha()

        stubs: list[dict] = []
        hit_known = False

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

                title_cell = cells[4]
                cell_text  = title_cell.get_text(separator=" ", strip=True)
                tender_id  = _extract_tender_id(cell_text)

                # ── early exit: hit territory we already have ────────────────
                if tender_id and tender_id in known_ids:
                    hit_known = True
                    return stubs, hit_known

                detail_link = title_cell.find("a", href=True)
                if not detail_link:
                    continue

                href = detail_link["href"]
                # skip navigation links — real detail pages contain service=direct
                if "service=direct" not in href:
                    continue

                detail_url = urljoin(self.base_url, href)
                stubs.append({
                    "title":      cell_text,
                    "detail_url": detail_url,
                    "tender_id":  tender_id,
                })

            # ── pagination ───────────────────────────────────────────────────
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

        return stubs, hit_known

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

        # ── generic td_caption / td_field pairs ─────────────────────────────
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

        # ── named sections ───────────────────────────────────────────────────
        self._parse_section(soup, "Work Item Details", data, cn, {
            "Title":                 "Title",
            "Work Description":      "Work Description",
            "NDA/Pre Qualification": "NDA/Pre Qualification",
            "Tender Value":          ("Tender Value in Rs", "number"),
            "Product Category":      "Product Category",
            "Sub category":          "Sub Category",
            "Bid Validity":          "Bid Validity(Days)",
            "Period Of Work":        "Period of Work(Days)",
            "Location":              "Location",
            "Pre Bid Meeting Place":    "Pre Bid Meeting Place",
            "Pre Bid Meeting Address":  "Pre Bid Meeting Address",
            "Pre Bid Meeting Date":     "Pre Bid Meeting Date",
            "Bid Opening Place":        "Bid Opening Place",
        })

        self._parse_section(soup, "Critical Dates", data, cn, {
            "Published Date":                      "Published Date",
            "Bid Opening Date":                    "Bid Opening Date",
            "Document Download / Sale Start Date": "Document Download / Sale Start Date",
            "Document Download / Sale End Date":   "Document Download / Sale End Date",
            "Clarification Start Date":            "Clarification Start Date",
            "Clarification End Date":              "Clarification End Date",
            "Bid Submission Start Date":           "Bid Submission Start Date",
            "Bid Submission End Date":             "Bid Submission End Date",
        })

        self._parse_section(soup, "Tender Inviting Authority", data, cn, {
            "Name":    "Tender Inviting Authority Name",
            "Address": "Tender Inviting Authority Address",
        })

        filled = sum(1 for v in data.values() if v)
        print(f"[{self.name}]   extracted {filled}/{len(FIXED_HEADERS)} fields")
        return data

    # ── private helpers ──────────────────────────────────────────────────────

    def _map_caption(self, data, caption, val, cn):
        cap_lower = caption.lower()
        if "organisation chain" in cap_lower:
            data["Organization Chain"] = val; return
        if "tender reference number" in cap_lower:
            data["Tender Reference Number"] = val; return
        if "tender id" in cap_lower:
            data["Tender ID"] = val; return

        for header in FIXED_HEADERS[4:]:
            h_lower = (
                header.lower()
                .replace(" in rs", "")
                .replace("(days)", "")
                .strip()
            )
            if h_lower in cap_lower or cap_lower in h_lower:
                data[header] = cn(val) if header in NUMERIC_FIELDS else val
                return

    def _parse_section(self, soup, section_label, data, cn, mapping):
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
