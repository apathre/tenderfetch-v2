"""
scrapers/psu_list_scrapers.py

Scrapers for PSU / nodal-agency sites that publish a plain tender list
rather than running the NIC GePNIC template (Phase 2 coverage, Nov 2026).
Structures were confirmed with the "Probe Sites" workflow from a GitHub
runner on 12 Nov 2026.

All of them fit BaseScraper's org -> list -> detail loop:

- fetch_org_list() returns one or more pseudo-orgs (a listing URL each).
- fetch_tender_list_incremental() parses every row of that listing, caches
  the row's fields, and returns the rows not seen before as stubs. These
  lists are short (tens of rows), so it never stops early on a known id.
- fetch_tender_detail() opens the site's detail page where one exists
  (POWERGRID, NTPC) and merges it over the cached row; for list-only sites
  (NGEL, THDC, PFCCL) it returns the cached row. A deadline re-check of an
  already-known tender reads the freshly cached row, so extended deadlines
  are still picked up.

Dates are normalised to the NIC format "17-Aug-2026 05:00 PM" (or
"17-Aug-2026" when the site gives no time), which output/db_writer.py
already parses into deadline_at.
"""

import re
import time
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core.base_scraper import BaseScraper

T_LOAD = 5
T_DETAIL = 3

_DATE_IN = (
    ("%a, %d-%b-%Y %I:%M %p", True),   # POWERGRID "Fri, 11-Dec-2026 11:00 AM"
    ("%d-%b-%Y %I:%M %p", True),
    ("%d %b %Y %I:%M %p", True),       # NTPC list "28 Nov 2026 1:00 PM"
    ("%d/%m/%Y :%H:%M", True),          # NTPC detail "28/11/2026 :13:00"
    ("%d/%m/%Y %H:%M", True),
    ("%d/%m/%Y %I:%M %p", True),
    ("%d.%m.%Y", False),
    ("%d-%m-%Y", False),
    ("%d/%m/%Y", False),               # NGEL, THDC "2/12/2026"
    ("%d-%b-%Y", False),
    ("%d %b %Y", False),
)


def nic_date(raw: str) -> str:
    """Normalise a site's date text to NIC format; '' if unparseable."""
    raw = re.sub(r"\s+", " ", (raw or "")).strip()
    if not raw:
        return ""
    # cut trailing noise such as "16 days left"
    raw = re.sub(r"\s*\d+\s+days?\s+left.*$", "", raw, flags=re.I).strip()
    for fmt, has_time in _DATE_IN:
        try:
            d = datetime.strptime(raw, fmt)
            return d.strftime("%d-%b-%Y %I:%M %p" if has_time else "%d-%b-%Y")
        except ValueError:
            continue
    return ""


def _txt(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip() if el else ""


# label (lower-case substring) -> FIXED_HEADERS column, first match wins
_LABELS = [
    ("tender reference", "Tender Reference Number"),
    ("nit no", "Tender Reference Number"),
    ("tender title", "Title"),
    ("brief nit description", "Title"),
    ("tender description", "Work Description"),
    ("description", "Work Description"),
    ("location of work", "Location"),
    ("state", "Location"),
    ("source of nit", "Organization Chain"),
    ("emd", "EMD Amount in Rs"),
    ("earnest money", "EMD Amount in Rs"),
    ("tender cost", "Tender Fee in Rs"),
    ("cost of document", "Tender Fee in Rs"),
    ("tender fee", "Tender Fee in Rs"),
    ("estimated", "Tender Value in Rs"),
    ("tender value", "Tender Value in Rs"),
    ("date of issue", "Published Date"),
    ("published", "Published Date"),
    ("sale start", "Document Download / Sale Start Date"),
    ("bid submission", "Bid Submission End Date"),
    ("closing date", "Bid Submission End Date"),
    ("doc collection", "Bid Submission End Date"),
    ("opening", "Bid Opening Date"),
    ("tender type", "Tender Type"),
    ("type of tender", "Tender Type"),
    ("category", "Tender Category"),
    ("pre bid", "Pre Bid Meeting Date"),
]
_DATE_COLS = {"Published Date", "Bid Submission End Date", "Bid Opening Date",
              "Document Download / Sale Start Date", "Pre Bid Meeting Date"}
_NUM_COLS = {"EMD Amount in Rs", "Tender Fee in Rs", "Tender Value in Rs"}


def map_label_pairs(tables) -> dict:
    """Read label/value cell pairs from detail tables into our columns."""
    out = {}
    for table in tables:
        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            for i in range(0, len(cells) - 1, 2):
                label = _txt(cells[i]).lower().rstrip(":").strip()
                value = _txt(cells[i + 1])
                if not label or not value:
                    continue
                label = label.split("/")[0].strip() or label   # drop Hindi after "/"
                for key, col in _LABELS:
                    if key in label and col not in out:
                        if col in _DATE_COLS:
                            value = nic_date(value) or value
                        if col in _NUM_COLS:
                            value = re.sub(r"[^\d.]", "", value)
                        if value:
                            out[col] = value
                        break
    return out


class _ListSiteScraper(BaseScraper):
    """Shared plumbing: row cache, page loading, DataTables 'show all'."""

    def __init__(self, driver, source):
        super().__init__(driver, source)
        self._rows: dict[str, dict] = {}

    def _soup(self, url: str, wait: float = T_LOAD) -> BeautifulSoup:
        self.driver.get(url)
        time.sleep(wait)
        return BeautifulSoup(self.driver.page_source, "html.parser")

    def _show_all_datatable(self, table_id: str) -> None:
        # client-side DataTables keep only the visible page in the DOM
        try:
            self.driver.execute_script(
                f"if (window.jQuery && jQuery.fn.dataTable && jQuery('#{table_id}').length)"
                f"{{ jQuery('#{table_id}').DataTable().page.len(-1).draw(); }}")
            time.sleep(2)
        except Exception as e:
            print(f"[{self.name}] could not expand table {table_id}: {e}")

    def _emit(self, rows: list[dict], known_ids: set[str]) -> tuple[list[dict], bool]:
        stubs, hit_known = [], False
        for r in rows:
            self._rows[r["Tender Detail URL"]] = r
            if r["Tender ID"] in known_ids:
                hit_known = True
                continue
            stubs.append({"tender_id": r["Tender ID"], "title": r.get("Title", ""),
                          "detail_url": r["Tender Detail URL"]})
        return stubs, hit_known

    def fetch_tender_detail(self, detail_url: str) -> dict:
        return dict(self._rows.get(detail_url, {}))


# ── POWERGRID ────────────────────────────────────────────────────────────────

class PowergridScraper(_ListSiteScraper):
    """apps.powergrid.in public tender portal. Daily runs read the
    last-7-days view; the full archive (8,000+) is never walked."""

    LIST_PATH = "/pgciltenders/u/view-published-tender.aspx?dt=sevendays"

    def fetch_org_list(self) -> list[dict]:
        return [{"org_name": "POWERGRID", "tender_count": "",
                 "org_url": urljoin(self.base_url, self.LIST_PATH)}]

    def fetch_tender_list_incremental(self, org_url, known_ids):
        self._soup(org_url)
        self._show_all_datatable("b_gData")
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        table = soup.find("table", id="b_gData")
        if not table:
            raise RuntimeError(f"[{self.name}] tender table #b_gData not found")
        rows = []
        for tr in table.find_all("tr")[1:]:
            tds = tr.find_all("td")
            if len(tds) < 6:
                continue
            link = tds[5].find("a", href=True)
            if not link:
                continue
            ref_title = _txt(tds[2])
            ref, _, title = ref_title.partition(" / ")
            closing, _, opening = _txt(tds[3]).partition(" / ")
            url = urljoin(org_url, link["href"])
            rows.append({
                "Tender ID": ref.strip() or url.rsplit("tid=", 1)[-1],
                "Tender Reference Number": ref.strip(),
                "Title": title.strip() or ref_title,
                "Location": _txt(tds[1]),
                "Bid Submission End Date": nic_date(closing),
                "Bid Opening Date": nic_date(opening),
                "Published Date": nic_date(_txt(tds[4])),
                "Tender Detail URL": url,
            })
        print(f"[{self.name}] listing has {len(rows)} tenders")
        return self._emit(rows, known_ids)

    def fetch_tender_detail(self, detail_url):
        rec = super().fetch_tender_detail(detail_url)
        soup = self._soup(detail_url, T_DETAIL)
        detail = map_label_pairs(soup.find_all("table")[:1])
        # list row wins for identity fields; detail fills the rest
        for k, v in detail.items():
            if k not in ("Tender ID",) and (not rec.get(k) or k == "Work Description"):
                rec[k] = v
        rec["Tender Detail URL"] = detail_url
        return rec


# ── NTPC ─────────────────────────────────────────────────────────────────────

class NTPCTenderScraper(_ListSiteScraper):
    """ntpctender.ntpc.co.in — NTPC's own tender notice portal (bids run on
    its SAP SRM or GeM). One pseudo-org per NTPC region listing; NTPC's
    eprocurentpc.nic.in GePNIC portal is a separate source ("NTPC")."""

    REGIONS = {
        1: "Corporate Center", 2: "Coal Mining Region", 3: "DBF & Hydro Region",
        4: "Eastern Region-I", 5: "Eastern Region-II", 6: "Northern Region",
        7: "Southern Region", 8: "Western Region-I", 9: "Western Region-II",
        10: "Renewable Energy", 11: "Consultancy Wing", 12: "JVs & Subsidaries",
    }

    def fetch_org_list(self) -> list[dict]:
        return [{"org_name": f"NTPC - {name}", "tender_count": "",
                 "org_url": urljoin(self.base_url, f"/Index/Search?Type=Reg&Region={rid}")}
                for rid, name in self.REGIONS.items()]

    def fetch_tender_list_incremental(self, org_url, known_ids):
        soup = self._soup(org_url)
        table = soup.find("table", id="TenderLists") or soup.find("table", class_="tender-table")
        if not table:
            print(f"[{self.name}] no tender table at {org_url}")
            return [], False
        rows = []
        for tr in table.find_all("tr")[1:]:
            tds = tr.find_all("td")
            if len(tds) < 5:
                continue
            link = tr.find("a", href=re.compile(r"NITDetails", re.I))
            if not link:
                continue
            url = urljoin(org_url, link["href"])
            ref = _txt(tds[1])
            rows.append({
                "Tender ID": f"NTPC-{url.rstrip('/').rsplit('/', 1)[-1]}",
                "Tender Reference Number": ref,
                "Title": _txt(tds[2]),
                "Organization Chain": _txt(tds[3]),
                "Bid Submission End Date": nic_date(_txt(tds[4])),
                "Tender Detail URL": url,
            })
        return self._emit(rows, known_ids)

    def fetch_tender_detail(self, detail_url):
        rec = super().fetch_tender_detail(detail_url)
        soup = self._soup(detail_url, T_DETAIL)
        detail = map_label_pairs(soup.find_all("table", class_="DtTable"))
        brief = detail.pop("Title", "")
        if brief and len(brief) > len(rec.get("Title", "")):
            rec["Work Description"] = brief
        for k, v in detail.items():
            if not rec.get(k):
                rec[k] = v
        rec["Tender Detail URL"] = detail_url
        return rec


# ── NGEL (NTPC Green Energy) ─────────────────────────────────────────────────

class NGELScraper(_ListSiteScraper):
    """ngel.in/tender — NTPC Green / NTPC REL RE tenders (WTGs, modules,
    BESS, solar EPC). Single table, NIT PDF per row, no detail page."""

    def fetch_org_list(self) -> list[dict]:
        return [{"org_name": "NTPC Green Energy Limited", "tender_count": "",
                 "org_url": urljoin(self.base_url, "/tender")}]

    def fetch_tender_list_incremental(self, org_url, known_ids):
        self._soup(org_url)
        self._show_all_datatable("myTable")
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        table = soup.find("table", id="myTable")
        if not table:
            raise RuntimeError(f"[{self.name}] tender table #myTable not found")
        rows = []
        for tr in table.find_all("tr")[1:]:
            tds = tr.find_all("td")
            if len(tds) < 6:
                continue
            ref = _txt(tds[1])
            nit = next((a for a in tr.find_all("a", href=True) if _txt(a).upper() == "NIT"), None)
            url = urljoin(org_url, nit["href"]) if nit else f"{org_url}#{ref}"
            rows.append({
                "Tender ID": ref,
                "Tender Reference Number": ref,
                "Title": _txt(tds[2]),
                "Published Date": nic_date(_txt(tds[3])),
                "Bid Submission End Date": nic_date(_txt(tds[4])),
                "Bid Opening Date": nic_date(_txt(tds[5])),
                "Tender Detail URL": url,
            })
        print(f"[{self.name}] listing has {len(rows)} tenders")
        return self._emit(rows, known_ids)


# ── THDC ─────────────────────────────────────────────────────────────────────

class THDCScraper(_ListSiteScraper):
    """thdc.co.in/en/tender — Drupal table (Title, Last Date, PDF),
    paginated ?page=0..N. Walks pages until one has no rows."""

    MAX_PAGES = 10

    def fetch_org_list(self) -> list[dict]:
        return [{"org_name": "THDC India Limited", "tender_count": "",
                 "org_url": urljoin(self.base_url, "/en/tender")}]

    def fetch_tender_list_incremental(self, org_url, known_ids):
        rows = []
        for page in range(self.MAX_PAGES):
            soup = self._soup(f"{org_url}?page={page}", 3)
            table = soup.find("table")
            trs = table.find_all("tr")[1:] if table else []
            got = 0
            for tr in trs:
                tds = tr.find_all("td")
                if len(tds) < 3:
                    continue
                pdf = tr.find("a", href=True)
                if not pdf:
                    continue
                title = _txt(tds[1])
                url = urljoin(org_url, pdf["href"])
                ref = re.search(r"\(([^()]*(?:no|nit|cc|gem)[^()]*)\)\s*$", title, re.I)
                rows.append({
                    "Tender ID": "THDC-" + url.rsplit("/", 1)[-1].rsplit(".", 1)[0],
                    "Tender Reference Number": ref.group(1) if ref else "",
                    "Title": title,
                    "Bid Submission End Date": nic_date(_txt(tds[2])),
                    "Tender Detail URL": url,
                })
                got += 1
            if not got:
                break
        print(f"[{self.name}] listing has {len(rows)} tenders")
        return self._emit(rows, known_ids)


# ── PFC Consulting (TBCB bid process coordinator) ────────────────────────────

class PFCCLScraper(_ListSiteScraper):
    """pfcclindia.com — TBCB transmission RfP/RfQ notices appear as
    "What's New" items (newsDetails.php?ID=N) on the home page; each item
    page lists the RfP and its amendments as PDFs. PFCCL's own consultancy
    procurement (tender-new.php) is not power-sector work and is skipped."""

    NOTICE_RE = re.compile(r"request for (proposal|qualification)|\brf[pq]\b|tbcb|"
                           r"transmission service provider|bid process", re.I)

    def fetch_org_list(self) -> list[dict]:
        return [{"org_name": "PFC Consulting Limited", "tender_count": "",
                 "org_url": urljoin(self.base_url, "/index.php")}]

    def fetch_tender_list_incremental(self, org_url, known_ids):
        soup = self._soup(org_url)
        rows, seen = [], set()
        for a in soup.find_all("a", href=re.compile(r"newsDetails\.php\?ID=\d+", re.I)):
            title = _txt(a)
            url = urljoin(org_url, a["href"])
            if url in seen or not self.NOTICE_RE.search(title):
                continue
            seen.add(url)
            nid = re.search(r"ID=(\d+)", url).group(1)
            rows.append({
                "Tender ID": f"PFCCL-{nid}",
                "Title": title,
                "Tender Category": "TBCB",
                "Tender Detail URL": url,
            })
        print(f"[{self.name}] {len(rows)} RfP/RfQ notices on home page")
        return self._emit(rows, known_ids)

    def fetch_tender_detail(self, detail_url):
        rec = super().fetch_tender_detail(detail_url)
        soup = self._soup(detail_url, T_DETAIL)
        docs = [f"{_txt(a)}: {urljoin(detail_url, a['href'])}"
                for a in soup.find_all("a", href=re.compile(r"download/.+\.pdf", re.I))][:10]
        if docs:
            rec["Work Description"] = (rec.get("Title", "") + " | Documents: " + "; ".join(docs))[:4000]
        return rec


# ── REC Power Development & Consultancy (TBCB + RE generation) ───────────────

class RECPDCLScraper(_ListSiteScraper):
    """recpdcl.in — one table per listing: each row is a tender title (in
    English, though the site chrome is Hindi) followed by its NIT / RFP /
    amendment PDFs. Two listings: transmission TBCB schemes and RE
    generation tenders. The general /tenders page (mostly RECPDCL's own
    office procurement on GeM, titled in Hindi) is skipped."""

    LISTINGS = {
        "rectpcltender": "RECPDCL - Transmission (TBCB)",
        "regenerationtenders": "RECPDCL - RE Generation",
    }
    DOC_PRIORITY = re.compile(r"rfp|rfs|rfe|nit|request", re.I)

    def fetch_org_list(self) -> list[dict]:
        return [{"org_name": name, "tender_count": "", "org_url": urljoin(self.base_url, "/" + path)}
                for path, name in self.LISTINGS.items()]

    def fetch_tender_list_incremental(self, org_url, known_ids):
        soup = self._soup(org_url)
        table = soup.find("table", class_="table-bordered") or soup.find("table")
        if not table:
            raise RuntimeError(f"[{self.name}] tender table not found at {org_url}")
        rows = []
        for tr in table.find_all("tr"):
            links = [a for a in tr.find_all("a", href=True) if ".pdf" in a["href"].lower()]
            if not links:
                continue
            cell = BeautifulSoup(str(tr.find(["td", "th"])), "html.parser")
            for a in cell.find_all("a"):
                a.decompose()
            title = _txt(cell)
            if not title:
                continue
            main = next((a for a in links if self.DOC_PRIORITY.search(_txt(a) + a["href"])), links[0])
            url = urljoin(org_url, main["href"])
            docs = "; ".join(f"{_txt(a)}: {urljoin(org_url, a['href'])}" for a in links[:12])
            rows.append({
                "Tender ID": "RECPDCL-" + url.rsplit("/", 1)[-1].rsplit(".", 1)[0][:80],
                "Title": title,
                "Work Description": (title + " | Documents: " + docs)[:4000],
                "Tender Category": "TBCB" if "tpcl" in org_url else "",
                "Tender Detail URL": url,
            })
        print(f"[{self.name}] {org_url.rsplit('/', 1)[-1]}: {len(rows)} tenders")
        return self._emit(rows, known_ids)
