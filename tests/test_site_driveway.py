"""Driveway: cars are discovered on the sitemap's category pages (JSON-LD inventory) and keyed by
their sku; --browser adds the specs and equipment of the rendered car page."""
from vehicle_scraper.config import Settings
from vehicle_scraper.http import Response
from vehicle_scraper.sites.driveway import DrivewayScraper, trim_from_name

from .conftest import FIXTURES, FakeClient

SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.driveway.com/shop/used/suv/bmw/x4</loc></url>
  <url><loc>https://www.driveway.com/shop/used/suv/bmw/x4/gas</loc></url>
  <url><loc>https://www.driveway.com/articles/how-to-buy</loc></url>
</urlset>"""

JSONLD_ONLY = {
    'source_site': 'driveway',
    'source_url': 'https://www.driveway.com/shop/vehicle/85895316',
    'listing_id': '85895316',
    'price': 27000.0,
    'currency': 'USD',
    'mileage_km': 133651,
    'vehicle_type': 'SUV',
    'make': 'BMW',
    'model': 'X4',
    'trim': 'M40i',
    'model_year': 2021,
    'body_style': 'SUV',
    'fuel_type': 'Gasoline',
    'transmission_type': 'Automatic',
}


def _client(tmp_path):
    client = FakeClient({"/shop/used/suv/bmw/x4": "driveway_category.html",
                         "/shop/vehicle/": "driveway_vehicle.html"})
    sitemap = Response("https://www.driveway.com/shop-seo-sitemap.xml", 200, SITEMAP, {})
    get = client.get
    client.get = lambda url, **kw: sitemap if url.endswith("shop-seo-sitemap.xml") else get(url, **kw)
    client.render = lambda url, **kw: client.get(url)
    return client


def _fields(rec):
    return {k: v for k, v in rec.model_dump(exclude={"scraped_at", "parse_warnings"}).items() if v is not None}


def test_discover_reads_category_inventory_and_dedupes(cfg, tmp_path):
    listings = list(DrivewayScraper(cfg, client=_client(tmp_path)).discover())
    # Both category URLs serve the same 3 cars: each is yielded once, keyed by its sku.
    assert [l.listing_id for l in listings] == ["88216015", "87435547", "85895316"]
    assert listings[2].url == "https://www.driveway.com/shop/vehicle/85895316"
    assert listings[2].payload["name"] == "2021 BMW X4 M40i"


def test_discover_limit(cfg, tmp_path):
    assert len(list(DrivewayScraper(cfg, client=_client(tmp_path)).discover(limit=2))) == 2


def test_parse_from_jsonld_without_fetching(cfg, tmp_path):
    client = _client(tmp_path)
    s = DrivewayScraper(cfg, client=client)
    listing = list(s.discover())[2]
    n = len(client.calls)
    rec = s.parse(listing)
    assert len(client.calls) == n                      # the car page needs a browser: not fetched
    assert _fields(rec) == JSONLD_ONLY


def test_parse_with_browser_adds_specs_and_equipment(tmp_path):
    cfg = Settings(data_dir=tmp_path, request_delay_s=0, use_browser=True)
    s = DrivewayScraper(cfg, client=_client(tmp_path))
    rec = s.parse(list(s.discover())[2])
    got = _fields(rec)
    assert {k: got[k] for k in JSONLD_ONLY} == JSONLD_ONLY     # JSON-LD values are kept
    assert rec.engine_cylinders == 6 and rec.engine_displacement_l is None   # "Engine: 6 Cyl"
    assert rec.drivetrain == "AWD"
    assert rec.blind_spot_monitoring and rec.keyless_entry and rec.stability_control
    assert rec.parse_warnings == []


def test_trim_from_name():
    assert trim_from_name("2021 BMW X4 M40i", 2021, "BMW", "X4") == "M40i"
    assert trim_from_name("2025 BMW X4", 2025, "BMW", "X4") is None
    assert trim_from_name("2024 Chevrolet Silverado 1500 LT Trail Boss", 2024, "Chevrolet",
                          "Silverado 1500") == "LT Trail Boss"


def test_fixtures_have_no_vin():
    for name in ("driveway_category.html", "driveway_vehicle.html"):
        assert "5UX2V5C06M9E78199" not in (FIXTURES / name).read_text(encoding="utf-8")
