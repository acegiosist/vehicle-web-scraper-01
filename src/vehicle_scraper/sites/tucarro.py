"""TuCarro (Colombia / Venezuela) — https://tucarro.com

tucarro.com is only a country picker for tucarro.com.co (Colombia) and
tucarro.com.ve (Venezuela), both run by Mercado Libre. Their web pages send automated
visitors to an "account-verification" wall, so this scraper uses Mercado Libre's
OFFICIAL API instead (https://developers.mercadolibre.com):

  search: GET https://api.mercadolibre.com/sites/{SITE}/search?category={SITE}1744&offset=&limit=50
  item:   GET https://api.mercadolibre.com/items?ids=ID1,ID2,...   (multiget, up to 20)

Setup: create an app at developers.mercadolibre.com, get an access token, then set
ML_ACCESS_TOKEN (and ML_SITE_ID=MCO for Colombia or MLV for Venezuela) in .env.
Note: the public search API caps offset at ~1000 results per query; split by
brand/year filters (``extra_params``) to go deeper.
"""
from __future__ import annotations

from typing import Iterator, Optional

from ..mapping import RecordBuilder
from ..models import VehicleRecord
from .base import Listing, SiteScraper, register

API = "https://api.mercadolibre.com"

# Mercado Libre attribute IDs -> schema fields (everything else is mapped by its Spanish name)
ATTR_IDS = {
    "BRAND": "make", "MODEL": "model", "TRIM": "trim", "VEHICLE_YEAR": "model_year",
    "VEHICLE_BODY_TYPE": "body_style", "FUEL_TYPE": "fuel_type", "TRANSMISSION": "transmission_type",
    "TRACTION_CONTROL": "drivetrain", "DOORS": "doors", "PASSENGER_CAPACITY": "seats",
    "ENGINE_DISPLACEMENT": "engine_displacement_l", "POWER": "horsepower_hp", "KILOMETERS": "mileage_km",
    "ENGINE_CYLINDERS_NUMBER": "engine_cylinders", "FUEL_TANK_CAPACITY": "fuel_tank_capacity_l",
    "AIRBAGS_NUMBER": "airbags_count", "RIM_DIAMETER": "wheel_size_in", "TIRE_SIZE": "tire_size",
    "TRUNK_CAPACITY": "cargo_capacity_l", "AUTONOMY": "ev_range_km",
}


@register
class TuCarroScraper(SiteScraper):
    name = "tucarro"
    base_url = "https://tucarro.com"
    status = "needs-token"
    notes = "Uses the official Mercado Libre API (set ML_ACCESS_TOKEN)."

    def __init__(self, *a, extra_params: Optional[dict] = None, **kw):
        super().__init__(*a, **kw)
        self.site_id = self.cfg.ml_site_id.upper()
        self.country = {"MCO": "CO", "MLV": "VE"}.get(self.site_id, self.site_id)
        self.extra_params = extra_params or {}
        if not self.cfg.ml_access_token:
            raise RuntimeError("tucarro needs ML_ACCESS_TOKEN (Mercado Libre API). See README.")
        self.client.session.headers["Authorization"] = f"Bearer {self.cfg.ml_access_token}"
        # Official, authenticated API: governed by the API terms, not by robots.txt.
        self.client.robots_exempt.add("api.mercadolibre.com")

    def discover(self, limit: Optional[int] = None) -> Iterator[Listing]:
        offset, n = 0, 0
        while True:
            params = {"category": f"{self.site_id}1744", "offset": offset, "limit": 50, **self.extra_params}
            data = self.client.get(f"{API}/sites/{self.site_id}/search", params=params).json()
            results = data.get("results") or []
            if not results:
                return
            for it in results:
                yield Listing(it["id"], it.get("permalink") or "", payload=it)
                n += 1
                if limit is not None and n >= limit:
                    return
            offset += len(results)
            total = min((data.get("paging") or {}).get("total", 0), 1000)
            if offset >= total:
                return

    def parse(self, listing: Listing) -> VehicleRecord:
        res = self.client.get(f"{API}/items", params={"ids": listing.listing_id}).json()
        item = (res[0].get("body") if isinstance(res, list) and res else None) or listing.payload
        b = RecordBuilder(self.name, item.get("permalink") or listing.url, listing.listing_id)
        b.set("price", item.get("price"))
        b.set("currency", item.get("currency_id"))
        for attr in item.get("attributes") or []:
            value = attr.get("value_name")
            struct = attr.get("value_struct") or {}
            hint = f"{attr.get('name', '')} {struct.get('unit', '')}"
            field = ATTR_IDS.get(attr.get("id", ""))
            if field:
                b.set(field, struct.get("number", value) if field not in ("make", "model", "trim") else value, hint)
            else:
                b.add_pair(attr.get("name", ""), value)
        b.add_free_text(item.get("title"))
        return self.finish(b.build())
