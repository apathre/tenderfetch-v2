"""
scrapers/sjvn_scraper.py
SJVN Limited (sjvn.nic.in) — a Drupal site, not the NIC eProcure template.

- No real org hierarchy (the default tender list already mixes all of
  SJVN's internal "Contract Units" together) — but it has FAR more
  historical tenders than expected (300+ and counting, confirmed from a
  live run), so it's split into fixed-size page-range chunks rather than
  treated as one pseudo-org. base_scraper.py only writes/checkpoints
  *after* an org's tenders are fully fetched — one giant "SJVN" org meant
  a run had to fetch and detail-page every tender site-wide before saving
  anything, which blew past GitHub Actions' 60-minute job timeout on the
  very first run without ever writing a single row. Chunking reuses that
  same per-org write/resume machinery unchanged: each chunk of
  PAGES_PER_CHUNK pages is its own "org", so progress is saved every
  chunk, and an interrupted run resumes from the next chunk next time —
  the same graceful-degradation pattern CPPP's own large history relies on.
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
from urllib.parse import urljoin, urlparse, parse_qs

from bs4 import BeautifulSoup

from core.base_scraper import BaseScraper
from core.config import FIXED_HEADERS, NUMERIC_FIELDS

T_LIST_LOAD = 4
T_DETAIL = 3

PAGES_PER_CHUNK = 10

# Outer safety bound on total chunks, in case last-page detection ever
# fails and falls back to guessing — same reasoning as before: degrade to
# "stops early, logs it" rather than running until the job timeout kills it.
MAX_LIST_PAGES = 300

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
    # Returns one pseudo-"org" per PAGES_PER_CHUNK-page slice of the listing,
    # rather than one org for the whole site — see module docstring for why.
    # The chunk's page range is threaded through as query params on org_url
    # (the only channel BaseScraper's interface gives fetch_tender_list_
    # incremental to receive per-org context).
    def fetch_org_list(self) -> list[dict]:
        tender_url = urljoin(self.base_url, "/en/tender")
        last_page = self._get_last_page_index(tender_url)
        print(f"[{self.name}] Listing spans pages 0-{last_page} "
              f"({last_page // PAGES_PER_CHUNK + 1} chunk(s) of {PAGES_PER_CHUNK} pages)")

        # org_name is not just a log label — base_scraper.py writes it
        # straight into every tender's "Organisation" field, so it has to
        # stay the real org name ("SJVN") on every chunk, not something
        # like "SJVN pages 0-9" leaking into Discovery's UI. base_scraper's
        # own [i+1/total_orgs] progress index still distinguishes chunks in
        # the logs even though every org_name here is identical.
        orgs = []
        start = 0
        while start <= last_page:
            end = min(start + PAGES_PER_CHUNK - 1, last_page)
            orgs.append({
                "org_name": "SJVN",
                "tender_count": "",
                "org_url": f"{tender_url}?__chunk_start={start}&__chunk_end={end}",
            })
            start = end + 1
        return orgs

    def _get_last_page_index(self, tender_url: str) -> int:
        """Read the pager's "last page" link on page 0 to get the exact
        0-indexed final page — Drupal's default pager exposes this
        directly, so chunk boundaries don't need to guess a total."""
        try:
            self.driver.get(tender_url)
            time.sleep(T_LIST_LOAD)
            soup = BeautifulSoup(self.driver.page_source, "html.parser")
            last_link = soup.select_one("li.pager__item--last a")
            if last_link and last_link.get("href"):
                qs = parse_qs(urlparse(last_link["href"]).query)
                return min(int(qs.get("page", ["0"])[0]), MAX_LIST_PAGES - 1)
        except Exception as e:
            print(f"[{self.name}] Warning: could not read last page — {e}")
        # No "last page" link found (e.g. the whole listing fits on one
        # page) — fall back to just page 0.
        return 0

    # ── fetch_tender_list_incremental ────────────────────────────────────────
    def fetch_tender_list_incremental(
        self, org_url: str, known_ids: set[str]
    ) -> tuple[list[dict], bool]:
        parsed = urlparse(org_url)
        qs = parse_qs(parsed.query)
        chunk_start = int(qs.get("__chunk_start", ["0"])[0])
        chunk_end   = int(qs.get("__chunk_end", ["0"])[0])
        tender_url  = parsed._replace(query="").geturl()

        stubs: list[dict] = []
        hit_known = False

        for page in range(chunk_start, chunk_end + 1):
            self.driver.get(f"{tender_url}?page={page}")
            time.sleep(T_LIST_LOAD)
            self.page_has_captcha()

            soup = BeautifulSoup(self.driver.page_source, "html.parser")
            cards = soup.select("div.views-row")
            if not cards:
                break  # ran out of real pages (last chunk is often partial)

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
