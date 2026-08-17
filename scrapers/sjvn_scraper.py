"""
scrapers/sjvn_scraper.py
SJVN Limited (sjvn.nic.in) — a Drupal site, not the NIC eProcure template.

- One organisation (SJVN) — the default tender list already mixes all its
  internal "Contract Units" together, so no org hierarchy to walk.
- Pagination is a plain `?page=N` (0-indexed) query string — no JS click
  needed, unlike SECI.
- Listing cards give ref/location/title/NIT date/submission deadline;
  detail pages add little beyond a fuller description. SJVN rarely
  publishes EMD/fee figures on its own site (it routes bidders to GeM or
  its own e-tendering portal for that) — those fields stay blank here,
  same as any other field a portal just doesn't expose.
"""

import re
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core.base_scraper import BaseScraper
from core.config import FIXED_HEADERS, NUMERIC_FIELDS

T_LIST_LOAD = 4
T_DETAIL = 3

# Hard safety cap on the listing pagination loop. On a brand-new source's
# first-ever run, known_ids starts empty, so the usual early-exit-on-
# known-id never triggers — the loop only stops when a page has no cards
# or (normally) no "next" link. This bounds worst case: if SJVN's pager
# markup ever has an edge case this scraper's pager-detection doesn't
# handle (only verified against the current page-0 markup), it terminates
# instead of running until GitHub Actions' 60-minute job timeout kills it.
MAX_LIST_PAGES = 200

_REF_LOCATION_RE = re.compile(r"^(.*?)\s*\(Location\s*:-\s*(.*?)\)\s*$")

# Detail-page label -> FIXED_HEADERS column (includes the Hindi variant seen
# on some nodes — SJVN's content authoring is inconsistent about which
# language a given field's label ends up in, even on an /en/ URL).
_LABEL_MAP = {
    "tender number":            "Tender Reference Number",
    "tender title":             "Title",
    "location":                 "Location",
    "nit date":                 "Published Date",
    "last date of submission":  "Bid Submission End Date",
    "tender description":       "Work Description",
    "निविदा विवरण":              "Work Description",
}


class SJVNScraper(BaseScraper):

    # ── fetch_org_list ───────────────────────────────────────────────────────
    def fetch_org_list(self) -> list[dict]:
        return [{
            "org_name": "SJVN",
            "tender_count": "",
            "org_url": urljoin(self.base_url, "/en/tender"),
        }]

    # ── fetch_tender_list_incremental ────────────────────────────────────────
    def fetch_tender_list_incremental(
        self, org_url: str, known_ids: set[str]
    ) -> tuple[list[dict], bool]:
        stubs: list[dict] = []
        hit_known = False
        page = 0

        while page < MAX_LIST_PAGES:
            self.driver.get(f"{org_url}?page={page}")
            time.sleep(T_LIST_LOAD)
            self.page_has_captcha()

            if page % 10 == 0:
                print(f"[{self.name}]   listing page {page} — {len(stubs)} stub(s) so far")

            soup = BeautifulSoup(self.driver.page_source, "html.parser")
            cards = soup.select("div.views-row")
            if not cards:
                break

            for card in cards:
                header = card.find("th")
                if not header:
                    continue
                # Read only the <strong> text, not the whole <th> — a sibling
                # "NEW" badge <span> lives inside <th> too, and would get
                # appended onto the ref/location string (breaking the regex
                # match below, and worse, corrupting the tender_id used for
                # dedup — a "NEW" tender would get a different id than the
                # same tender re-scraped later once the badge disappears).
                strong = header.find("strong")
                header_text = self.clean_text((strong or header).get_text())
                m = _REF_LOCATION_RE.match(header_text)
                ref_no = m.group(1) if m else header_text

                link = card.find("a", href=True)
                if not link or not ref_no:
                    continue

                if ref_no in known_ids:
                    hit_known = True
                    return stubs, hit_known

                title_cell = card.select_one("tbody tr:first-child td")
                stubs.append({
                    "title":      self.clean_text(title_cell.get_text()) if title_cell else ref_no,
                    "detail_url": urljoin(self.base_url, link["href"]),
                    "tender_id":  ref_no,
                })

            # ── pagination: is there a "next page" link? ─────────────────────
            next_link = soup.select_one("nav.pager a[title='Go to next page'], li.pager__item--next a")
            if not next_link:
                break
            page += 1
        else:
            print(f"[{self.name}]   hit MAX_LIST_PAGES ({MAX_LIST_PAGES}) safety cap — stopping "
                  f"pagination early with {len(stubs)} stub(s) collected so far")

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

        table = soup.select_one("div.tender-detail-pg table")
        rows = table.find_all("tr") if table else []
        for tr in rows:
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            label = ct(tds[0].get_text()).lower().rstrip(':').strip()
            value = ct(tds[1].get_text())
            header = _LABEL_MAP.get(label)
            if header:
                data[header] = cn(value) if header in NUMERIC_FIELDS else value

        filled = sum(1 for v in data.values() if v)
        print(f"[{self.name}]   extracted {filled}/{len(FIXED_HEADERS)} fields")
        return data
