r"""www.driveway.com (US) — https://www.driveway.com

Discovery uses the search API the site's own /shop page calls
(``api-gateway.driveway.com/search-mgmt/v1/search/results``, with the public key its frontend
ships; override it with ``DRIVEWAY_API_KEY``). It is an internal API, not a documented one: used
at the user's request, through PoliteClient like everything else.

* Results are sorted "Newest Inventory" (``INVENTORY_NEWEST``) and each one carries its
  ``inventoryDate``, used as ``listed_at``: ``run --max-age`` filters on it like on the other
  sites, and paging stops at the first car older than the cutoff (the rest are older still).
* The API fails (HTTP 502) past ~30,000 results per query, so a group of conditions bigger than
  ``max_window`` is split into price ranges until each fits. Range bounds are inclusive, so cars
  priced exactly on a bound show up twice and are dropped as duplicates by ``vehicleId``.
* A result has year, make, model, trim, price, mileage (miles), fuel and MPG, but no body style,
  transmission or drivetrain. ``--browser`` renders the car page (``/shop/vehicle/<id>``) and
  reads its spec overview and equipment lists too.
* Not stored: the VIN and the dealership the API also returns.
"""
from __future__ import annotations

import os
from typing import Iterator, Optional

from .. import extract as X
from ..mapping import RecordBuilder
from ..models import VehicleRecord
from ..normalize import to_datetime
from .base import Listing, register
from .html_site import HtmlSiteScraper

SEARCH_URL = "https://api-gateway.driveway.com/search-mgmt/v1/search/results"
PUBLIC_KEY = "e6c1852eb5124b1890fbd17ad53e870a"      # shipped in driveway.com's own JavaScript


@register
class DrivewayScraper(HtmlSiteScraper):
    name = 'driveway'
    base_url = 'https://www.driveway.com'
    country = 'US'
    currency = 'USD'
    status = "unverified"
    notes = 'Internal search API sorted newest-first (inventoryDate); --browser adds specs/equipment'

    condition_groups: tuple[tuple[str, ...], ...] = (("CPO", "USED"), ("NEW",))
    page_size = 100
    max_window = 29_000                 # results one query can page through (the API 502s past ~30k)
    price_range = (0, 100_000_000)      # the whole inventory: used when a group has to be split
    # Spec overview + equipment tabs on the rendered car page (not the payment calculator).
    spec_selector = '[class*="DWVehicleDetailsTabs-wrapper"]'
    wait_selector = '[data-testid="category-features"]'

    # -- discovery -------------------------------------------------------------
    def _search(self, conditions, price: Optional[tuple[float, float]], skip: int, items: int) -> dict:
        filters: dict = {"vehicleConditions": list(conditions)}
        if price:
            filters["priceWithFeesRange"] = {"from": price[0], "to": price[1]}
        body = {"filters": filters, "vehicleConditions": list(conditions), "includeSimilar": False,
                "sort": "INVENTORY_NEWEST", "pagination": {"items": items, "skip": skip}}
        key = os.getenv("DRIVEWAY_API_KEY") or PUBLIC_KEY
        r = self.client.post(f"{SEARCH_URL}?key={key}", json=body,
                             headers={"Origin": self.base_url, "Referer": f"{self.base_url}/shop"})
        return r.json().get("exactMatch") or {}

    @staticmethod
    def _total(page: dict) -> int:
        return int((page.get("pageInfo") or {}).get("totalItems") or 0)

    def _partitions(self, conditions) -> Iterator[Optional[tuple[float, float]]]:
        """Price ranges (None = no price filter) that each fit in ``max_window`` results."""
        total = self._total(self._search(conditions, None, 0, 1))
        if total <= self.max_window:
            yield None
            return
        priced = self._total(self._search(conditions, self.price_range, 0, 1))
        if priced < total:
            self.log.warning("%d %s cars have no price and can't be reached when splitting by price",
                             total - priced, "/".join(conditions))
        stack = [self.price_range]
        while stack:
            lo, hi = stack.pop()
            n = self._total(self._search(conditions, (lo, hi), 0, 1))
            if n <= self.max_window or hi - lo < 1000:
                if n > self.max_window:
                    self.log.warning("price range %s-%s has %d cars; only the newest %d are reachable",
                                     lo, hi, n, self.max_window)
                yield (lo, hi)
            else:
                # Geometric midpoint: from 0-100M it reaches real car prices in a few splits.
                mid = max(lo + 1, min(hi - 1, round((max(lo, 1000) * hi) ** 0.5)))
                stack += [(mid, hi), (lo, mid)]       # bounds overlap by one price: deduped by id

    def _results(self, conditions, price) -> Iterator[dict]:
        skip = 0
        while skip < self.max_window:
            page = self._search(conditions, price, skip, self.page_size)
            results = page.get("results") or []
            yield from results
            skip += len(results)
            if not results or skip >= self._total(page):
                return

    def discover(self, limit: Optional[int] = None) -> Iterator[Listing]:
        seen: set[str] = set()
        for conditions in self.condition_groups:
            for price in self._partitions(conditions):
                for car in self._results(conditions, price):
                    vid = str(car.get("vehicleId") or "")
                    if not vid or vid in seen:
                        continue
                    seen.add(vid)
                    listed_at = to_datetime(car.get("inventoryDate"))
                    yield Listing(vid, f"{self.base_url}/shop/vehicle/{vid}", payload=car,
                                  listed_at=listed_at)
                    if limit is not None and len(seen) >= limit:
                        return
                    if self.listed_since and listed_at and listed_at < self.listed_since:
                        break                         # newest first: the rest of this range is older

    # -- parsing ---------------------------------------------------------------
    def parse(self, listing: Listing) -> VehicleRecord:
        b = RecordBuilder(self.name, listing.url, listing.listing_id)
        car = listing.payload or {}
        # Most reliable sources first: the first value set for a field wins.
        b.set("make", car.get("make"))
        b.set("model", car.get("model"))
        b.set("trim", car.get("trim"))
        b.set("model_year", car.get("year"))
        b.set("price", car.get("price"))
        b.set("currency", "USD")
        b.set("mileage_km", car.get("mileage"), "mi")
        b.set("fuel_type", car.get("fuel"))
        mpg = car.get("mpg") or {}
        if mpg.get("combined"):
            b.set("fuel_economy_kml", mpg["combined"], "mpg")
        if self.cfg.use_browser:
            soup = X.soup_of(self.fetch_html(listing.url, self.wait_selector))
            if soup.select_one(self.spec_selector):     # not the whole page: payment calculator noise
                X.apply_html(b, soup, self.spec_selector)
            else:
                b.warn("vehicle details section not found on the rendered page")
        b.add_title(car.get("trim"))                    # "Crew Cab 4x4": body/drivetrain tokens only
        return self.finish(b.build())
