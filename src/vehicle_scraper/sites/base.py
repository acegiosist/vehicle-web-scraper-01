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
from typing import Any, Iterator, Optional
from xml.etree import ElementTree as ET

from ..config import Settings, settings as default_settings
from ..http import PoliteClient
from ..models import VehicleRecord

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


class SiteScraper(ABC):
    name: str = ""
    base_url: str = ""
    country: str = ""
    currency: Optional[str] = None        # overrides a wrong/missing currency on the site
    warn_currency_mismatch: bool = True   # False when the site's reported currency is known-wrong
    status: str = "verified"              # verified | needs-token | blocked-by-site | unverified
    notes: str = ""
    extra_headers: dict = {}

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

    def sitemap_urls(self, sitemap_url: str, pattern: str, _depth: int = 0) -> Iterator[str]:
        """Yield URLs matching ``pattern`` from a sitemap (follows sitemap indexes)."""
        xml = self.client.get(sitemap_url).text
        try:
            root = ET.fromstring(xml.encode())
        except ET.ParseError:
            self.log.warning("could not parse sitemap %s", sitemap_url)
            return
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        for loc in root.findall(".//s:sitemap/s:loc", ns):
            if _depth < 3:
                yield from self.sitemap_urls(loc.text.strip(), pattern, _depth + 1)
        rx = re.compile(pattern)
        for loc in root.findall(".//s:url/s:loc", ns):
            url = (loc.text or "").strip()
            if rx.search(url):
                yield url

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
