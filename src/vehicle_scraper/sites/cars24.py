r"""www.cars24.com — https://www.cars24.com

Scaffolded by `vehicle_scraper new-site` on 2026-11-18 from https://www.cars24.com/
* Discovery: sitemap https://www.cars24.com/sitemap.xml, detail URLs like /buy-used-<model>-<year>-cars-<city>-<id>/
  (29,251 in the sitemap on 2026-11-19).
* Detail page: JSON-LD Car: yes; embedded JSON specs: no; spec section: none found, reads the whole page.
* Warning: country unknown from the domain; pass --country (ISO code)
"""
from __future__ import annotations

from .. import extract as X
from ..mapping import RecordBuilder
from ..models import VehicleRecord
from .base import Listing, register
from .html_site import HtmlSiteScraper


@register
class Cars24Scraper(HtmlSiteScraper):
    name = 'cars24'
    base_url = 'https://www.cars24.com'
    country = ''
    currency = None
    status = "unverified"
    notes = 'Scaffolded by new-site; review before marking verified'

    sitemap_url = 'https://www.cars24.com/sitemap.xml'
    # Only used-car detail pages. A looser /[a-z0-9-]+-\d+/ also matches ~2,360 news, article,
    # new-car and RTO-registration pages in the sitemap.
    sitemap_pattern = r"/buy-used-[a-z0-9-]+-\d+/?$"
    id_pattern = r"-(\d+)/?$"

    def parse(self, listing: Listing) -> VehicleRecord:
        soup = X.soup_of(self.fetch_html(listing.url, self.wait_selector))
        b = RecordBuilder(self.name, listing.url, listing.listing_id)

        # Most reliable sources first: the first value set for a field wins.
        for car in X.jsonld_vehicles(soup):
            X.apply_jsonld(b, car)
        X.apply_html(b, soup)   # label/value pairs and equipment lists anywhere in <main>

        title = soup.find("h1") or soup.find("title")
        if title:
            b.add_title(title.get_text(" ", strip=True))
        desc = soup.find("meta", attrs={"name": "description"})
        if desc and desc.get("content"):
            b.add_free_text(desc["content"])

        # TODO: labels on the sample pages that don't map to the schema yet. If one matters, add
        # a synonym to mapping.LABEL_RULES / FEATURE_PATTERNS (with a test) or handle it here.
        #   Buy Used Cars in Bulandshahar
        #   Loan against car
        #   Personal loan
        #   Car services
        #   Call us
        #   Hello, Sign in Account
        #   Hello, Sign in
        #   Reasons to buy this car
        #   Top features of this car
        #   Why buy from verified sellers?
        #   Essential features
        #   Top model
        #   Previous
        #   Reg. year
        #   KM driven
        return self.finish(b.build())
