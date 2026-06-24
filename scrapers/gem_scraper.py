"""
scrapers/gem_scraper.py
Stub for GeM (Government e-Marketplace) bid scraping.
GeM uses a completely different SPA structure, so it gets its own scraper class.

Implement fetch_org_list / fetch_tender_list / fetch_tender_detail
following the same interface as CPPPScraper.
"""

from core.base_scraper import BaseScraper


class GeMScraper(BaseScraper):

    def fetch_org_list(self) -> list[dict]:
        # TODO: GeM uses /api/v2/bids  – JSON API, not HTML tables
        raise NotImplementedError("GeMScraper.fetch_org_list not yet implemented")

    def fetch_tender_list(self, org_url: str) -> list[dict]:
        raise NotImplementedError

    def fetch_tender_detail(self, detail_url: str) -> dict:
        raise NotImplementedError
