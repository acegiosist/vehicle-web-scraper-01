r"""www.truecar.com (US) — https://www.truecar.com

Scaffolded by `vehicle_scraper new-site` on 2026-11-18 from https://www.truecar.com/
* Discovery: sitemap https://www.truecar.com/sitemaps/used/used-sitemap-index.xml, detail URLs like /used-cars-for-sale/listing/[A-Za-z0-9-]+/[a-z0-9-]+/?$ (2403 seen while probing).
* Detail page: JSON-LD Car: yes; embedded JSON specs: yes; spec section: none found, reads the whole page.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Iterator

from .. import extract as X
from ..mapping import RecordBuilder, match_label
from ..models import VehicleRecord
from .base import Listing, register
from .html_site import HtmlSiteScraper


def _truecar_pairs(pairs: Iterable[tuple[str, Any]]) -> Iterator[tuple[str, Any]]:
    """TrueCar's embedded JSON writes booleans as "t"/"f" and drops the ft³ unit on
    cargo volumes (its HTML shows "24.3 ft³" for the same value)."""
    for label, value in pairs:
        if isinstance(value, str) and value.strip().lower() in ("t", "f"):
            value = "true" if value.strip().lower() == "t" else "false"
        elif match_label(str(label)) == "cargo_capacity_l" and re.fullmatch(r"\s*\d+(\.\d+)?\s*", str(value)):
            value = f"{str(value).strip()} ft³"
        yield label, value


@register
class TruecarScraper(HtmlSiteScraper):
    name = 'truecar'
    base_url = 'https://www.truecar.com'
    country = 'US'
    currency = 'USD'
    status = "unverified"
    notes = 'Scaffolded by new-site; review before marking verified'

    sitemap_url = 'https://www.truecar.com/sitemaps/used/used-sitemap-index.xml'
    sitemap_pattern = r"/used-cars-for-sale/listing/[A-Za-z0-9-]+/[a-z0-9-]+/?$"
    id_pattern = r"/([A-Za-z0-9-]+)/[a-z0-9-]+/?$"

    def parse(self, listing: Listing) -> VehicleRecord:
        soup = X.soup_of(self.fetch_html(listing.url, self.wait_selector))
        b = RecordBuilder(self.name, listing.url, listing.listing_id)

        # Most reliable sources first: the first value set for a field wins.
        for car in X.jsonld_vehicles(soup):
            X.apply_jsonld(b, car)
        for blob in X.embedded_json(soup):
            b.add_pairs(_truecar_pairs(X.walk_json_pairs(blob)))
        X.apply_html(b, soup)   # label/value pairs and equipment lists anywhere in <main>

        title = soup.find("h1") or soup.find("title")
        if title:
            b.add_title(title.get_text(" ", strip=True))
        desc = soup.find("meta", attrs={"name": "description"})
        if desc and desc.get("content"):
            b.add_free_text(desc["content"])

        return self.finish(b.build())
