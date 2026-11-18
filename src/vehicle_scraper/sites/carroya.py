"""CarroYa (Colombia) — https://www.carroya.com

Verified Nov 2026. The web app is a React SPA backed by a public JSON API:
* Search:  POST https://carroya-habilitadora-api.avaldigitallabs.com/find-filters
           body {"seoArray": [], "params": {"page": "1", "status": "usado"}, "isReqForRedirect": false}
           -> results.superHighlights[] (20 per page, each with an ``id``), ``pages``
* Detail:  GET  https://carroya-habilitadora-api.avaldigitallabs.com/find-vehicle-detail/<id>
           -> data.{brand, model, version, year, cylindrical, box, fuel, accessories[],
                    main-features[{name, description}],
                    technical_sheet[{autopart, specifications[{name, value}]}]}

Personal data in the API (plate, seller name/phone/email) is deliberately dropped.
"""
from __future__ import annotations

import re
from typing import Iterator, Optional

from ..mapping import RecordBuilder
from ..normalize import strip_accents
from ..models import VehicleRecord
from .base import Listing, SiteScraper, register

API = "https://carroya-habilitadora-api.avaldigitallabs.com"


def _slug(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "-", strip_accents(str(value)).lower()).strip("-")


@register
class CarroYaScraper(SiteScraper):
    name = "carroya"
    base_url = "https://www.carroya.com"
    country = "CO"
    currency = "COP"
    notes = "Best coverage: technical sheet + accessories via JSON API."
    extra_headers = {
        "Origin": "https://www.carroya.com",
        "Referer": "https://www.carroya.com/",
        "Accept": "application/json, text/plain, */*",
    }

    def __init__(self, *a, status: str = "usado", **kw):
        super().__init__(*a, **kw)
        self.status_filter = status          # "usado" | "nuevo"

    def discover(self, limit: Optional[int] = None) -> Iterator[Listing]:
        page, pages, n = 1, None, 0
        seen: set[str] = set()
        while pages is None or page <= pages:
            body = {"seoArray": [], "params": {"page": str(page), "status": self.status_filter,
                                               "sort": "publication-date-desc"}, "isReqForRedirect": False}
            data = self.client.post(f"{API}/find-filters", json=body).json()
            pages = int(data.get("pages") or 0)
            items = (data.get("results") or {}).get("superHighlights") or []
            if not items:
                break
            for it in items:
                vid = it.get("id")
                if not vid or vid in seen:
                    continue
                seen.add(vid)
                yield Listing(vid, f"{self.base_url}/detalle/{self.status_filter}/x/x/0/x/{vid}")
                n += 1
                if limit is not None and n >= limit:
                    return
            self.log.info("page %d/%d done (%d listings)", page, pages, n)
            page += 1

    def parse(self, listing: Listing) -> VehicleRecord:
        d = self.client.get(f"{API}/find-vehicle-detail/{listing.listing_id}").json().get("data") or {}
        parts = [d.get("status") or self.status_filter, d.get("brand"), d.get("model"), d.get("year"), d.get("city")]
        url = (f"{self.base_url}/detalle/" + "/".join(_slug(p) for p in parts) + f"/{listing.listing_id}"
               if all(parts) else listing.url)
        b = RecordBuilder(self.name, url, listing.listing_id)

        # 1) Structured top-level fields (most reliable)
        b.set("make", d.get("brand"))
        b.set("model", d.get("model"))
        b.set("trim", d.get("version"))
        b.set("model_year", d.get("year"))
        b.set("engine_displacement_l", d.get("cylindrical"), "cc")
        b.set("transmission_type", d.get("box"))
        b.set("fuel_type", d.get("fuel"))
        b.set("mileage_km", d.get("kilometers"))
        b.set("price", d.get("price"))

        # 2) main-features: [{"name": "Wheel drive", "description": "4x4"}, ...]
        for f in d.get("main-features") or []:
            b.add_pair(f.get("name", ""), f.get("description"))

        # 3) technical sheet: grouped specs with S/N booleans
        for group in d.get("technical_sheet") or []:
            for spec in group.get("specifications") or []:
                b.add_pair(spec.get("name", ""), spec.get("value"))

        # 4) model + version text: sellers often leave "Bodywork"/"Wheel drive" blank but
        #    write "2.0 Sedan Touring Aut" or "IX35 4x4" in the version.
        b.add_title(d.get("model"), d.get("version"))

        # 5) accessories = equipment present on this car
        b.add_feature_list([a.strip() for a in d.get("accessories") or []])

        # 6) seller comments (only adds clearly mentioned features)
        b.add_free_text(d.get("comments"))
        return self.finish(b.build())
