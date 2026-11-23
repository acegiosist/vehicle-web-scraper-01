r"""www.driveway.com (US) — https://www.driveway.com

Uses two internal APIs the site's own pages call on ``api-gateway.driveway.com``, with the public
key its frontend ships (override it with ``DRIVEWAY_API_KEY``). They are not documented APIs:
used at the user's request, through PoliteClient like everything else.

* Discovery: the search API behind /shop (``search-mgmt/v1/search/results``), sorted "Newest
  Inventory" (``INVENTORY_NEWEST``). Each result carries its ``inventoryDate``, used as
  ``listed_at``: ``run --max-age`` filters on it like on the other sites, and paging stops at the
  first car older than the cutoff (the rest are older still).
* The search API fails (HTTP 502) past ~30,000 results per query, so a group of conditions
  bigger than ``max_window`` is split into price ranges until each fits. Range bounds are
  inclusive, so cars priced exactly on a bound show up twice and are dropped as duplicates by
  ``vehicleId``. The ranges are merged by date, so the stream stays newest first as a whole.
* A full run (no ``--limit``, with or without ``--max-age``) fetches the whole list before parsing: parsing takes days, and
  paging by offset while cars are sold would shift the pages and skip cars.
* Parsing: the search result (year, make, model, trim, price, mileage in miles, fuel, MPG) plus
  the car page's GraphQL query (``shop/gql/v5/graphql``, ``getVehicleById``) for the overview
  (body, doors, engine, transmission, drive type) and every equipment list the page shows. No
  browser needed; ``--browser`` changes nothing here.
* Not requested or stored: the VIN and the dealership.
"""
from __future__ import annotations

import heapq
import os
from typing import Iterator, Optional

from ..mapping import RecordBuilder
from ..models import VehicleRecord
from ..normalize import to_datetime
from .base import Listing, SiteScraper, register

API = "https://api-gateway.driveway.com"
SEARCH_URL = f"{API}/search-mgmt/v1/search/results"
GRAPHQL_URL = f"{API}/shop/gql/v5/graphql"
PUBLIC_KEY = "e6c1852eb5124b1890fbd17ad53e870a"      # shipped in driveway.com's own JavaScript

# Only what the record needs (the page's own query also asks for the VIN, dealership, images...).
DETAIL_QUERY = """query GetVehicle($id: String!) {
  getVehicleById(id: $id) {
    bodyStyle bedStyle cabStyle doors engine transmission driveType fuel
    mpg { highway city }
    categoryFeatures { category features }
  }
}"""


@register
class DrivewayScraper(SiteScraper):
    name = 'driveway'
    base_url = 'https://www.driveway.com'
    country = 'US'
    currency = 'USD'
    status = "unverified"
    notes = 'Internal search API sorted newest-first (inventoryDate) + GraphQL car details'

    condition_groups: tuple[tuple[str, ...], ...] = (("CPO", "USED"), ("NEW",))
    page_size = 100
    max_window = 29_000                 # results one query can page through (the API 502s past ~30k)
    price_range = (0, 100_000_000)      # the whole inventory: used when a group has to be split

    @property
    def _key(self) -> str:
        return os.getenv("DRIVEWAY_API_KEY") or PUBLIC_KEY

    def _headers(self) -> dict:
        return {"Origin": self.base_url, "Referer": f"{self.base_url}/shop"}

    # -- discovery -------------------------------------------------------------
    def _search(self, conditions, price: Optional[tuple[float, float]], skip: int, items: int) -> dict:
        filters: dict = {"vehicleConditions": list(conditions)}
        if price:
            filters["priceWithFeesRange"] = {"from": price[0], "to": price[1]}
        body = {"filters": filters, "vehicleConditions": list(conditions), "includeSimilar": False,
                "sort": "INVENTORY_NEWEST", "pagination": {"items": items, "skip": skip}}
        r = self.client.post(f"{SEARCH_URL}?key={self._key}", json=body, headers=self._headers())
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
            last = to_datetime(results[-1].get("inventoryDate"))
            if self.listed_since and last and last < self.listed_since:
                return                                # newest first: later pages are older still

    def discover(self, limit: Optional[int] = None) -> Iterator[Listing]:
        ranges: list = [self._results(conditions, price)
                        for conditions in self.condition_groups for price in self._partitions(conditions)]
        if limit is None and self.run_limit is None:
            # A full run parses for days: take the whole list now, before sold cars shift the pages.
            ranges = [list(r) for r in ranges]
            self.log.info("fetched %d search results in %d price ranges", sum(map(len, ranges)), len(ranges))
        # Every range is sorted newest first; merging them by inventoryDate keeps the whole
        # stream newest first, so --limit takes the newest cars of all ranges (not of the first)
        # and the first car older than --max-age means every car still to come is older too.
        seen: set[str] = set()
        for car in heapq.merge(*ranges, key=lambda c: c.get("inventoryDate") or "", reverse=True):
            vid = str(car.get("vehicleId") or "")
            if not vid or vid in seen:
                continue
            seen.add(vid)
            listed_at = to_datetime(car.get("inventoryDate"))
            yield Listing(vid, f"{self.base_url}/shop/vehicle/{vid}", payload=car, listed_at=listed_at)
            if limit is not None and len(seen) >= limit:
                return
            if self.listed_since and listed_at and listed_at < self.listed_since:
                return                                # run_site counts this one as too old

    # -- parsing ---------------------------------------------------------------
    def _detail(self, vehicle_id: str) -> dict:
        r = self.client.post(GRAPHQL_URL, json={"query": DETAIL_QUERY, "variables": {"id": vehicle_id}},
                             headers={**self._headers(), "Ocp-Apim-Subscription-Key": self._key})
        data = r.json()
        car = (data.get("data") or {}).get("getVehicleById")
        if not car:
            errors = "; ".join(e.get("message", "") for e in data.get("errors") or [])
            raise ValueError(f"no details for vehicle {vehicle_id} (sold?): {errors or 'empty answer'}")
        return car

    def parse(self, listing: Listing) -> VehicleRecord:
        b = RecordBuilder(self.name, listing.url, listing.listing_id)
        car = listing.payload or {}
        detail = self._detail(listing.listing_id)
        # Most reliable sources first: the first value set for a field wins.
        b.set("make", car.get("make"))
        b.set("model", car.get("model"))
        b.set("trim", car.get("trim"))
        b.set("model_year", car.get("year"))
        b.set("price", car.get("price"))
        b.set("currency", "USD")
        b.set("mileage_km", car.get("mileage"), "mi")
        b.add_pairs([("Body", detail.get("bodyStyle")), ("Doors", detail.get("doors")),
                     ("Engine", detail.get("engine")), ("Fuel Type", detail.get("fuel") or car.get("fuel")),
                     ("Transmission", detail.get("transmission")), ("Drive Type", detail.get("driveType"))])
        mpg = car.get("mpg") or {}
        if mpg.get("combined"):
            b.set("fuel_economy_kml", mpg["combined"], "mpg")
        for group in detail.get("categoryFeatures") or []:
            b.add_feature_list(group.get("features") or [])
        b.add_title(car.get("trim"), detail.get("cabStyle"))   # "Crew Cab", "4x4": body/drive tokens
        return self.finish(b.build())
