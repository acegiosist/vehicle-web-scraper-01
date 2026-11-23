r"""www.driveway.com (US) — https://www.driveway.com

Scaffolded by `vehicle_scraper new-site` on 2026-11-23, then rewritten by hand:
* The sitemaps only list SEO category pages (``/shop/used/suv/bmw/x4``,
  ``/shop/new/truck/ram/2500/diesel``), never single cars. Each category page is server-rendered
  and carries ``pageProps.inventoryJsonLd`` in ``__NEXT_DATA__``: a schema.org ItemList of up to
  24 ``Vehicle``s (make, model, name with the trim, year, price in USD, odometer in miles,
  fuel, transmission, body). Discovery walks those pages and yields each car once, by its
  ``sku``, with its JSON-LD as the payload.
* The car's own page (``/shop/vehicle/<sku>``) is rendered in the browser: without JavaScript
  it only has the title. With ``--browser`` the spec overview (engine, drive type, body...) and
  the equipment lists are read from it too; without it the record comes from the JSON-LD alone.
* No listing date anywhere, so ``run --max-age`` saves nothing for this site.
"""
from __future__ import annotations

import json
import re
from typing import Iterator, Optional

from .. import extract as X
from ..mapping import RecordBuilder
from ..models import VehicleRecord
from .base import Listing, register
from .html_site import HtmlSiteScraper


def inventory_vehicles(html: str) -> list[dict]:
    """The schema.org Vehicles a category page lists (``pageProps.inventoryJsonLd``)."""
    nd = X.soup_of(html).find("script", id="__NEXT_DATA__")
    try:
        data = json.loads(nd.string) if nd and nd.string else {}
    except json.JSONDecodeError:
        return []
    inv = ((data.get("props") or {}).get("pageProps") or {}).get("inventoryJsonLd") or {}
    out = []
    for el in inv.get("itemListElement") or []:
        item = el.get("item") if isinstance(el, dict) else None
        if isinstance(item, dict) and item.get("sku"):
            out.append(item)
    return out


def trim_from_name(name: Optional[str], year, make: Optional[str], model: Optional[str]) -> Optional[str]:
    """"2021 BMW X4 M40i" -> "M40i": what follows year, make and model in the JSON-LD name."""
    if not (name and make and model):
        return None
    prefix = r"\s+".join(re.escape(str(p)) for p in (year, make, model) if p)
    m = re.match(rf"\s*{prefix}\s+(.+?)\s*$", name, re.I)
    return m.group(1) if m else None


@register
class DrivewayScraper(HtmlSiteScraper):
    name = 'driveway'
    base_url = 'https://www.driveway.com'
    country = 'US'
    currency = 'USD'
    status = "unverified"
    notes = 'Category pages from the sitemap -> JSON-LD inventory; --browser adds specs/equipment'

    sitemap_url = 'https://www.driveway.com/shop-seo-sitemap.xml'
    sitemap_pattern = r"/shop/(new|used)/"          # category pages; the cars are listed inside
    id_pattern = r"/shop/vehicle/(\d+)"
    # Spec overview + equipment tabs on the rendered car page (not the payment calculator).
    spec_selector = '[class*="DWVehicleDetailsTabs-wrapper"]'
    wait_selector = '[data-testid="category-features"]'

    def discover(self, limit: Optional[int] = None) -> Iterator[Listing]:
        seen: set[str] = set()
        for page_url in self.sitemap_urls(self.sitemap_url, self.sitemap_pattern):
            # Category pages are server-rendered: plain HTTP even under --browser.
            for car in inventory_vehicles(self.client.get(page_url).text):
                sku = str(car["sku"])
                if sku in seen:
                    continue
                seen.add(sku)
                offers = car.get("offers")
                offer = offers[0] if isinstance(offers, list) and offers else offers
                url = (offer or {}).get("url") if isinstance(offer, dict) else None
                yield Listing(sku, url or f"{self.base_url}/shop/vehicle/{sku}", payload=car)
                if limit is not None and len(seen) >= limit:
                    return

    def parse(self, listing: Listing) -> VehicleRecord:
        b = RecordBuilder(self.name, listing.url, listing.listing_id)
        car = listing.payload or {}
        # Most reliable sources first: the first value set for a field wins.
        if car:
            X.apply_jsonld(b, car)
        if self.cfg.use_browser:
            soup = X.soup_of(self.fetch_html(listing.url, self.wait_selector))
            if soup.select_one(self.spec_selector):     # not the whole page: payment calculator noise
                X.apply_html(b, soup, self.spec_selector)
            else:
                b.warn("vehicle details section not found on the rendered page")
        if car:
            brand = car.get("brand")
            make = brand.get("name") if isinstance(brand, dict) else brand
            b.set("trim", trim_from_name(car.get("name"), car.get("vehicleModelDate"), make, car.get("model")))
            b.add_title(car.get("name"))
        return self.finish(b.build())
