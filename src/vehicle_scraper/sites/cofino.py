"""Cofiño Usados (Guatemala) — https://cofinousados.com

Verified Nov 2026:
* Discovery: /sitemap.xml lists every /catalogo/<slug>-<code> page.
* Detail page: schema.org ``Car`` JSON-LD + a "Detalles del auto" list
  (Transmisión, Combustible, Kilometraje, Motor, Año, Tracción, ...).
* JSON-LD says priceCurrency "MXN" but prices are in quetzales (Q) -> GTQ.
"""
from __future__ import annotations

import re
from typing import Iterator, Optional

from .. import extract as X
from ..mapping import RecordBuilder
from ..models import VehicleRecord
from .base import Listing, SiteScraper, register, take


@register
class CofinoScraper(SiteScraper):
    name = "cofino"
    base_url = "https://cofinousados.com"
    country = "GT"
    currency = "GTQ"
    notes = "Dealer site; publishes few specs (no equipment list)."

    def discover(self, limit: Optional[int] = None) -> Iterator[Listing]:
        urls = self.sitemap_urls(f"{self.base_url}/sitemap.xml", r"/catalogo/[a-z0-9-]+-\d+/?$")
        for url in take(urls, limit):
            code = re.search(r"-(\d+)/?$", url).group(1)
            yield Listing(listing_id=code, url=url)

    def parse(self, listing: Listing) -> VehicleRecord:
        html = self.fetch_html(listing.url, wait_selector="h2")
        soup = X.soup_of(html)
        b = RecordBuilder(self.name, listing.url, listing.listing_id)

        for car in X.jsonld_vehicles(soup):
            X.apply_jsonld(b, car)

        # "Detalles del auto" section: <li><svg/><span>Label</span><span>Value</span></li>
        section = None
        for h in soup.find_all(["h2", "h3"]):
            if "detalles del auto" in h.get_text(" ", strip=True).lower():
                section = h.parent
                break
        if section is not None:
            b.add_pairs(X.html_pairs(section))
        else:
            b.warn("'Detalles del auto' section not found")
            X.apply_html(b, soup)

        desc = soup.find("meta", attrs={"name": "description"})
        if desc and desc.get("content"):
            b.add_free_text(desc["content"])
        return self.finish(b.build())
