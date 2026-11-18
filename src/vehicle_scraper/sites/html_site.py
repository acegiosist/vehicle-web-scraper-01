"""Reusable scraper for 'normal' HTML car sites, plus the YAML-configured GenericScraper.

Discovery: a sitemap (+ URL regex) or listing pages (+ link regex + pagination).
Parsing:   JSON-LD Car -> embedded JSON (__NEXT_DATA__ etc.) -> HTML spec tables/lists.
"""
from __future__ import annotations

import re
from typing import Iterator, Optional
from urllib.parse import urljoin

from .. import extract as X
from ..mapping import RecordBuilder
from ..models import VehicleRecord
from .base import Listing, SiteScraper, take


class HtmlSiteScraper(SiteScraper):
    # Discovery ---------------------------------------------------------------
    sitemap_url: Optional[str] = None
    sitemap_pattern: str = ""
    start_urls: list[str] = []
    page_url_template: Optional[str] = None     # e.g. "https://x.com/autos?page={page}"
    first_page: int = 1
    max_pages: int = 500
    link_pattern: str = ""                       # regex on absolute detail URLs
    id_pattern: str = r"(\d{5,})/?$"             # regex with one group -> listing_id
    # Parsing -----------------------------------------------------------------
    spec_selector: Optional[str] = None          # CSS selector of the spec area (optional)
    wait_selector: Optional[str] = None          # for Playwright rendering

    def _listing_id(self, url: str) -> str:
        m = re.search(self.id_pattern, url)
        return m.group(1) if m else url.rstrip("/").rsplit("/", 1)[-1]

    def _links(self, page_url: str) -> list[str]:
        soup = X.soup_of(self.fetch_html(page_url, self.wait_selector))
        rx = re.compile(self.link_pattern)
        out, seen = [], set()
        for a in soup.find_all("a", href=True):
            url = urljoin(page_url, a["href"]).split("#")[0].split("?")[0]
            if rx.search(url) and url not in seen:
                seen.add(url)
                out.append(url)
        return out

    def _page_urls(self) -> Iterator[str]:
        yield from self.start_urls
        if self.page_url_template:
            for p in range(self.first_page, self.first_page + self.max_pages):
                yield self.page_url_template.format(page=p, offset=(p - self.first_page) * 12)

    def discover(self, limit: Optional[int] = None) -> Iterator[Listing]:
        if self.sitemap_url:
            for url in take(self.sitemap_urls(self.sitemap_url, self.sitemap_pattern), limit):
                yield Listing(self._listing_id(url), url)
            return
        seen: set[str] = set()
        for page_url in self._page_urls():
            links = [u for u in self._links(page_url) if u not in seen]
            if not links:
                self.log.info("no new listings on %s, stopping", page_url)
                return
            for url in links:
                seen.add(url)
                yield Listing(self._listing_id(url), url)
                if limit is not None and len(seen) >= limit:
                    return

    def parse(self, listing: Listing) -> VehicleRecord:
        soup = X.soup_of(self.fetch_html(listing.url, self.wait_selector))
        b = RecordBuilder(self.name, listing.url, listing.listing_id)
        for car in X.jsonld_vehicles(soup):
            X.apply_jsonld(b, car)
        for blob in X.embedded_json(soup):
            b.add_pairs(X.walk_json_pairs(blob))
        X.apply_html(b, soup, self.spec_selector)
        self.post_parse(b, soup)
        return self.finish(b.build())

    def post_parse(self, b: RecordBuilder, soup) -> None:
        """Hook for site-specific tweaks."""


class GenericScraper(HtmlSiteScraper):
    """A site defined entirely in config/sites.yaml — no Python needed."""

    status = "unverified"

    @classmethod
    def from_config(cls, cfg_dict: dict) -> type["GenericScraper"]:
        attrs = {k: v for k, v in cfg_dict.items() if k != "type"}
        attrs.setdefault("notes", "Configured in sites.yaml")
        return type(f"Generic_{cfg_dict['name']}", (cls,), attrs)
