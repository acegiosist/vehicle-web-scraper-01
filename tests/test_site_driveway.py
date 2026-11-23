"""Driveway: discovery through the site's search API sorted newest-first (inventoryDate is the
listing date), split by price when a query has more results than it can page through."""
from json import dumps as json_dumps
from datetime import date, datetime, timedelta, timezone

from vehicle_scraper.config import Settings
from vehicle_scraper.http import Response
from vehicle_scraper.sites.base import Listing
from vehicle_scraper.sites.driveway import DrivewayScraper

from .conftest import FIXTURES

CAR = {   # one search result as the API returns it (VIN and dealership left out on purpose)
    "vehicleId": "85895316", "year": 2021, "make": "BMW", "model": "X4", "trim": "M40i",
    "condition": "USED", "mileage": 83047, "price": 27000.0, "priceWithFees": 27799.0,
    "inventoryDate": "2026-11-18", "fuel": "Gas", "exteriorColor": {"name": "Black"},
    "mpg": {"city": 21, "combined": 23, "highway": 27},
}
EXPECTED = {
    'source_site': 'driveway',
    'source_url': 'https://www.driveway.com/shop/vehicle/85895316',
    'listing_id': '85895316',
    'price': 27000.0,
    'currency': 'USD',
    'mileage_km': 133651,
    'make': 'BMW',
    'model': 'X4',
    'trim': 'M40i',
    'model_year': 2021,
    'fuel_type': 'Gasoline',
    'fuel_economy_kml': 9.8,
}


def _inventory(n_used=5, n_new=7, start=date(2026, 11, 22)):
    """Cars newest first, one day apart; new cars priced 10k..70k."""
    cars = []
    for i in range(n_used):
        cars.append({"vehicleId": str(100 + i), "condition": "USED", "year": 2022, "make": "Ford",
                     "model": "F-150", "price": 30000.0 + i, "priceWithFees": 30000.0 + i,
                     "inventoryDate": (start - timedelta(days=i)).isoformat()})
    for i in range(n_new):
        p = 10000.0 * (i + 1)
        cars.append({"vehicleId": str(200 + i), "condition": "NEW", "year": 2026, "make": "Ford",
                     "model": "Bronco", "price": p, "priceWithFees": p,
                     "inventoryDate": (start - timedelta(days=i)).isoformat()})
    return cars


class FakeApi:
    """The search endpoint: filters by condition and inclusive price range, newest first,
    and errors past ``window`` results like the real one."""

    def __init__(self, cars, window=10_000):
        self.cars, self.window, self.bodies = cars, window, []
        self.session = type("S", (), {"headers": {}})()
        self.robots_exempt: set[str] = set()

    def post(self, url, json=None, **kw):
        self.bodies.append(json)
        conds = set(json["filters"]["vehicleConditions"])
        rng = json["filters"].get("priceWithFeesRange")
        hits = [c for c in self.cars if c["condition"] in conds
                and (rng is None or rng["from"] <= c["priceWithFees"] <= rng["to"])]
        hits.sort(key=lambda c: c["inventoryDate"], reverse=True)
        skip, items = json["pagination"]["skip"], json["pagination"]["items"]
        assert skip + items <= self.window + items, "deep page: the real API answers 502"
        body = {"exactMatch": {"results": hits[skip:skip + items],
                               "pageInfo": {"skip": skip, "items": items, "totalItems": len(hits)}}}
        return Response(url, 200, json_dumps(body), {})

    def get(self, url, **kw):
        assert "/shop/vehicle/" in url, url
        return Response(url, 200, (FIXTURES / "driveway_vehicle.html").read_text(encoding="utf-8"), {})

    render = get

    def close(self):
        pass


def _scraper(cfg, api, **attrs):
    s = DrivewayScraper(cfg, client=api)
    for k, v in attrs.items():
        setattr(s, k, v)
    return s


def _fields(rec):
    return {k: v for k, v in rec.model_dump(exclude={"scraped_at", "parse_warnings"}).items() if v is not None}


def test_discover_newest_first_with_inventory_date(cfg):
    api = FakeApi(_inventory())
    listings = list(_scraper(cfg, api, page_size=2).discover())
    assert len(listings) == 12
    dates = [l.listed_at for l in listings]
    assert dates == sorted(dates, reverse=True)         # used and new interleaved, newest first
    assert {l.listing_id for l in listings[:2]} == {"100", "200"}   # both from 22 Nov
    assert listings[0].listed_at == datetime(2026, 11, 22, tzinfo=timezone.utc)
    assert listings[0].url == "https://www.driveway.com/shop/vehicle/100"
    assert all(b["sort"] == "INVENTORY_NEWEST" for b in api.bodies)


def test_discover_limit(cfg):
    assert len(list(_scraper(cfg, FakeApi(_inventory()), page_size=2).discover(limit=3))) == 3


def test_max_age_stops_paging_at_first_older_car(cfg):
    api = FakeApi(_inventory(n_used=50, n_new=0))
    s = _scraper(cfg, api, page_size=5, listed_since=datetime(2026, 11, 20, tzinfo=timezone.utc))
    ids = [l.listing_id for l in s.discover()]
    # 22, 21, 20 Nov pass; 19 Nov is yielded (run_site counts it as too old), then paging stops.
    assert ids == ["100", "101", "102", "103"]
    used_pages = [b for b in api.bodies if b["filters"]["vehicleConditions"] == ["CPO", "USED"]
                  and b["pagination"]["items"] == 5]
    assert len(used_pages) == 1                         # not the other 9 pages


def test_big_group_is_split_by_price_and_deduped(cfg):
    api = FakeApi(_inventory(n_used=2, n_new=7), window=3)
    s = _scraper(cfg, api, page_size=2, max_window=3, price_range=(0, 80000))
    ids = [l.listing_id for l in s.discover()]
    assert sorted(ids) == sorted({c["vehicleId"] for c in api.cars})   # every car, once
    ranges = {tuple(b["filters"]["priceWithFeesRange"].values()) for b in api.bodies
              if "priceWithFeesRange" in b["filters"]}
    assert ranges and all(lo >= 0 and hi <= 80000 for lo, hi in ranges)


def test_limit_takes_newest_across_price_ranges(cfg):
    # The cheapest new cars are the oldest: the newest 3 sit in the dearer ranges.
    cars = _inventory(n_used=0, n_new=7)
    for c in cars:
        c["inventoryDate"] = (date(2026, 11, 22) - timedelta(days=int(70000 - c["price"]) // 10000)).isoformat()
    api = FakeApi(cars, window=3)
    s = _scraper(cfg, api, page_size=2, max_window=3, price_range=(0, 80000))
    got = [l.payload["price"] for l in s.discover(limit=3)]
    assert got == [70000.0, 60000.0, 50000.0]


def test_parse_from_search_result_without_fetching(cfg):
    api = FakeApi([])
    s = _scraper(cfg, api)
    assert _fields(s.parse(_listing(CAR))) == EXPECTED
    assert api.bodies == []                             # nothing fetched without --browser


def test_parse_with_browser_adds_specs_and_equipment(tmp_path):
    cfg = Settings(data_dir=tmp_path, request_delay_s=0, use_browser=True)
    rec = _scraper(cfg, FakeApi([])).parse(_listing(CAR))
    got = _fields(rec)
    assert {k: got[k] for k in EXPECTED} == EXPECTED    # API values are kept
    assert rec.body_style == "SUV" and rec.transmission_type == "Automatic"
    assert rec.engine_cylinders == 6 and rec.engine_displacement_l is None   # "Engine: 6 Cyl"
    assert rec.drivetrain == "AWD"
    assert rec.blind_spot_monitoring and rec.keyless_entry and rec.stability_control
    assert rec.parse_warnings == []


def test_fixture_has_no_vin():
    assert "5UX2V5C06M9E78199" not in (FIXTURES / "driveway_vehicle.html").read_text(encoding="utf-8")


def _listing(car):
    return Listing(car["vehicleId"], f"https://www.driveway.com/shop/vehicle/{car['vehicleId']}",
                   payload=car)
