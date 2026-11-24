"""Base class and registry for site scrapers.

A site scraper only has to implement two methods:

    discover()      -> yields Listing(listing_id, url, payload)
    parse(listing)  -> VehicleRecord

Register it with ``@register`` and it becomes available in the CLI.
"""
from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterator, Optional
from xml.etree import ElementTree as ET

from ..config import Settings, settings as default_settings
from ..http import PoliteClient
from ..models import VehicleRecord
from ..normalize import to_datetime

log = logging.getLogger(__name__)

REGISTRY: dict[str, type["SiteScraper"]] = {}


def register(cls: type["SiteScraper"]) -> type["SiteScraper"]:
    REGISTRY[cls.name] = cls
    return cls


@dataclass
class Listing:
    listing_id: str
    url: str
    payload: dict = field(default_factory=dict)   # anything discover() already knows
    # When the listing was posted (UTC), if the site says. Set by discover() when known up front
    # (API field, sitemap <lastmod>) so `run --max-age` can skip old listings without fetching
    # them; parse() may overwrite it with a better date found on the detail page.
    listed_at: Optional[datetime] = None


class SiteScraper(ABC):
    name: str = ""
    base_url: str = ""
    country: str = ""
    currency: Optional[str] = None        # overrides a wrong/missing currency on the site
    warn_currency_mismatch: bool = True   # False when the site's reported currency is known-wrong
    status: str = "verified"              # verified | needs-token | blocked-by-site | unverified
    notes: str = ""
    extra_headers: dict = {}
    # Set by `run --max-age` before discover(): the cutoff (UTC). run_site applies it either way;
    # a scraper whose discovery is sorted newest-first may also use it to stop paging early.
    listed_since: Optional[datetime] = None
    # The run's --limit (None = whole site). Under --max-age discover() is called without a limit,
    # since run_site keeps going until `limit` listings pass the filter.
    run_limit: Optional[int] = None
    # Set by `run --ids-file`: only these listing ids are parsed (re-extraction after a parser
    # fix). A scraper that prefetches details in batches (Driveway) asks only for these.
    only_ids: Optional[set[str]] = None

    def __init__(self, cfg: Settings = default_settings, client: Optional[PoliteClient] = None):
        self.cfg = cfg
        self.client = client or PoliteClient(cfg, extra_headers=self.extra_headers)
        self.log = logging.getLogger(f"site.{self.name}")

    @abstractmethod
    def discover(self, limit: Optional[int] = None) -> Iterator[Listing]:
        """Yield listings to scrape (stop after ``limit`` if given)."""

    @abstractmethod
    def parse(self, listing: Listing) -> VehicleRecord:
        """Fetch (if needed) and normalize one listing."""

    # -- shared helpers --------------------------------------------------------
    def fetch_html(self, url: str, wait_selector: Optional[str] = None) -> str:
        if self.cfg.use_browser:
            return self.client.render(url, wait_selector=wait_selector).text
        return self.client.get(url).text

    def sitemap_urls(self, sitemap_url: str, pattern: str) -> Iterator[str]:
        """Yield URLs matching ``pattern`` from a sitemap (follows sitemap indexes)."""
        for url, _ in self.sitemap_entries(sitemap_url, pattern):
            yield url

    def sitemap_entries(self, sitemap_url: str, pattern: str,
                        _depth: int = 0) -> Iterator[tuple[str, Optional[datetime]]]:
        """Like ``sitemap_urls`` but also yields each URL's ``<lastmod>`` (UTC) or None."""
        xml = self.client.get(sitemap_url).text
        try:
            root = ET.fromstring(xml.encode())
        except ET.ParseError:
            self.log.warning("could not parse sitemap %s", sitemap_url)
            return
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        for loc in root.findall(".//s:sitemap/s:loc", ns):
            if _depth < 3:
                yield from self.sitemap_entries(loc.text.strip(), pattern, _depth + 1)
        rx = re.compile(pattern)
        for node in root.findall(".//s:url", ns):
            url = (node.findtext("s:loc", "", ns) or "").strip()
            if rx.search(url):
                yield url, to_datetime(node.findtext("s:lastmod", None, ns))

    def finish(self, record: VehicleRecord) -> VehicleRecord:
        if self.currency and (record.currency is None or record.currency != self.currency):
            if record.currency and record.currency != self.currency and self.warn_currency_mismatch:
                record.parse_warnings.append(f"site reported currency {record.currency}; using {self.currency}")
            record.currency = self.currency
        return record

    def close(self) -> None:
        self.client.close()


def take(it: Iterator[Any], limit: Optional[int]) -> Iterator[Any]:
    for i, x in enumerate(it):
        if limit is not None and i >= limit:
            return
        yield x
