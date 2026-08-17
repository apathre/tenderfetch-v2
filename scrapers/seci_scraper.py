"""
scrapers/seci_scraper.py
Solar Energy Corporation of India (seci.co.in) — a standalone site, not the
NIC eProcure template. Structurally much simpler than CPPP:

- One organisation (SECI itself) — no org hierarchy to walk.
- A single DataTables.js-rendered table, paginated via JS button clicks
  (no page-numbered URLs), sorted S.No. ascending == newest first.
- Detail pages are clean label/value <td> pairs, two pairs per <tr>,
  label cells marked with class="fw-bold".
"""

import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By

from core.base_scraper import BaseScraper
from core.config import FIXED_HEADERS, NUMERIC_FIELDS

T_LIST_LOAD = 5
T_PAGE_CLICK = 3
T_DETAIL = 3

# Detail-page label -> FIXED_HEADERS column. SECI's label set is small and
# fixed, so an exact dict lookup is simpler and less error-prone here than
# the fuzzy substring matching CPPPScraper uses for NIC eProcure's much
# larger, looser label set.
_LABEL_MAP = {
    "tender id":                    "Tender ID",
    "tender reference no":          "Tender Reference Number",
    "tender title":                 "Title",
    "tender type":                  "Tender Type",
    "tender description":           "Work Description",
    "tender fee/bid processing fee": "Tender Fee in Rs",
    "emd":                          "EMD Amount in Rs",
    "tender publication date":      "Published Date",
    "pre bid meeting date":         "Pre Bid Meeting Date",
    "bid submission end date (online)": "Bid Submission End Date",
    "bid open date":                "Bid Opening Date",
}


class SECIScraper(BaseScraper):

    # ── fetch_org_list ───────────────────────────────────────────────────────
    # SECI is one organisation — a single pseudo-org keeps this compatible
    # with BaseScraper.scrape()'s per-org resume/write loop without changes.
    def fetch_org_list(self) -> list[dict]:
        return [{
            "org_name": "SECI",
            "tender_count": "",
            "org_url": urljoin(self.base_url, "/tenders/"),
        }]

    # ── fetch_tender_list_incremental ────────────────────────────────────────
    def fetch_tender_list_incremental(
        self, org_url: str, known_ids: set[str]
    ) -> tuple[list[dict], bool]:
        self.driver.get(org_url)
        time.sleep(T_LIST_LOAD)
        self.page_has_captcha()

        stubs: list[dict] = []
        hit_known = False

        while True:
            soup = BeautifulSoup(self.driver.page_source, "html.parser")
            table = soup.find("table", id="tender-list")
            rows = table.find("tbody").find_all("tr") if table else []

            for tr in rows:
                cells = tr.find_all("td")
                if len(cells) < 8:
                    continue

                tender_id = self.clean_text(cells[1].get_text())
                if tender_id and tender_id in known_ids:
                    hit_known = True
                    return stubs, hit_known

                link = cells[7].find("a", href=True)
                if not link:
                    continue

                stubs.append({
                    "title":      self.clean_text(cells[4].get_text()),
                    "detail_url": urljoin(self.base_url, link["href"]),
                    "tender_id":  tender_id,
                })

            # ── pagination (DataTables JS button, not a URL) ─────────────────
            try:
                next_btn = self.driver.find_element(
                    By.CSS_SELECTOR, "nav[aria-label='pagination'] .dt-paging-button.next"
                )
                if "disabled" in (next_btn.get_attribute("class") or ""):
                    break
                next_btn.click()
                time.sleep(T_PAGE_CLICK)
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

        for tr in soup.find_all("tr"):
            tds = tr.find_all("td")
            i = 0
            while i < len(tds) - 1:
                cell = tds[i]
                if "fw-bold" in (cell.get("class") or []):
                    label = ct(cell.get_text()).lower().rstrip(':').strip()
                    value = ct(tds[i + 1].get_text())
                    header = _LABEL_MAP.get(label)
                    if header:
                        data[header] = cn(value) if header in NUMERIC_FIELDS else value
                    i += 2
                else:
                    i += 1

        filled = sum(1 for v in data.values() if v)
        print(f"[{self.name}]   extracted {filled}/{len(FIXED_HEADERS)} fields")
        return data
