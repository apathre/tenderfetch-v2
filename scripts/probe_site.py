"""
scripts/probe_site.py

Diagnostic for adding a new tender source: loads each URL in a real Chrome
on the GitHub runner (the same place the scraper will run) and prints what
a scraper needs to know — whether the site is reachable from there, the
final URL and title, the tables on the page with their first rows, and the
links that look like tenders, documents or pagination.

Run it from Actions → "Probe Sites" with a space-separated URL list, or
locally:  python scripts/probe_site.py URL [URL ...]
"""

import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bs4 import BeautifulSoup  # noqa: E402

from core.driver import get_driver  # noqa: E402

LINK_HINT = re.compile(
    r"tender|nit\b|rfp|rfs|rfq|bid|eoi|notice|corrigend|\.pdf|page=|pageno|next|›|»|archive|active|"
    r"last\s*\d+\s*days|all tenders|search",
    re.IGNORECASE,
)


def cell_text(c, n=50):
    return re.sub(r"\s+", " ", c.get_text(" ", strip=True))[:n]


def probe(driver, url):
    print("=" * 100)
    print(f"PROBE {url}")
    try:
        driver.get(url)
        time.sleep(6)
    except Exception as e:
        print(f"  LOAD ERROR: {e}")
        return
    soup = BeautifulSoup(driver.page_source, "html.parser")
    body = soup.get_text(" ", strip=True)
    print(f"  final url : {driver.current_url}")
    print(f"  title     : {soup.title.get_text(strip=True) if soup.title else '-'}")
    print(f"  html size : {len(driver.page_source)} chars, text {len(body)} chars")
    print(f"  text head : {body[:300]}")

    tables = soup.find_all("table")
    print(f"  tables    : {len(tables)}")
    for ti, t in enumerate(tables[:15]):
        rows = t.find_all("tr")
        attrs = {k: v for k, v in t.attrs.items() if k in ("id", "class")}
        print(f"   table {ti} {attrs} rows={len(rows)}")
        for tr in rows[:4]:
            cells = tr.find_all(["td", "th"])
            print(f"      {[cell_text(c) for c in cells[:7]]}")
            for a in tr.find_all("a", href=True)[:3]:
                print(f"        a: {cell_text(a, 40)!r} -> {urljoin(driver.current_url, a['href'])[:160]}")

    # card / list layouts (no tables)
    for sel in ("div.views-row", "li.list-group-item", "div.card", "article", "div.tender", "div[class*=tender]"):
        items = soup.select(sel)
        if len(items) >= 3:
            print(f"  repeated '{sel}': {len(items)} items; first two:")
            for it in items[:2]:
                print(f"      {cell_text(it, 250)!r}")
                for a in it.find_all("a", href=True)[:3]:
                    print(f"        a: {cell_text(a, 40)!r} -> {urljoin(driver.current_url, a['href'])[:160]}")

    seen, shown = set(), 0
    print("  tender-ish links:")
    for a in soup.find_all("a", href=True):
        href = urljoin(driver.current_url, a["href"])
        text = cell_text(a, 60)
        if href in seen or not (LINK_HINT.search(text) or LINK_HINT.search(href)):
            continue
        seen.add(href)
        print(f"      {text!r} -> {href[:180]}")
        shown += 1
        if shown >= 45:
            break
    forms = soup.find_all("form")
    if forms:
        print(f"  forms     : {[(f.get('id'), f.get('action')) for f in forms[:5]]}")


def main(urls):
    driver = get_driver(headless=True)
    try:
        for u in urls:
            probe(driver, u)
    finally:
        driver.quit()


if __name__ == "__main__":
    main(sys.argv[1:])
