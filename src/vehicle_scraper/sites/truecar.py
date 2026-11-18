r"""www.truecar.com (US) — https://www.truecar.com

Scaffolded by `vehicle_scraper new-site` on 2026-11-18 from https://www.truecar.com/
* Discovery: sitemap https://www.truecar.com/sitemaps/used/used-sitemap-index.xml, detail URLs like /used-cars-for-sale/listing/[A-Za-z0-9-]+/[a-z0-9-]+/?$ (2403 seen while probing).
* Detail page: JSON-LD Car: yes; embedded JSON specs: yes; spec section: none found, reads the whole page.
"""
from __future__ import annotations

from .. import extract as X
from ..mapping import RecordBuilder
from ..models import VehicleRecord
from .base import Listing, register
from .html_site import HtmlSiteScraper


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
            b.add_pairs(X.walk_json_pairs(blob))
        X.apply_html(b, soup)   # label/value pairs and equipment lists anywhere in <main>

        title = soup.find("h1") or soup.find("title")
        if title:
            b.add_title(title.get_text(" ", strip=True))
        desc = soup.find("meta", attrs={"name": "description"})
        if desc and desc.get("content"):
            b.add_free_text(desc["content"])

        # TODO: labels on the sample pages that don't map to the schema yet. If one matters, add
        # a synonym to mapping.LABEL_RULES / FEATURE_PATTERNS (with a test) or handle it here.
        #   Advertised price
        #   Filing Fee
        #   Documentation Fee
        #   Dealer asking price
        #   Front Brake Diameter
        #   Rear Brake Diameter
        #   First Gear Ratio
        #   Second Gear Ratio
        #   Third Gear Ratio
        #   Fourth Gear Ratio
        #   Fifth Gear Ratio
        #   Sixth Gear Ratio
        #   Reverse Gear Ratio
        #   Final Drive Axle Ratio
        #   Front Head Room
        return self.finish(b.build())
