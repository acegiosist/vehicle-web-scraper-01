"""Snapshot of what the cars24 scraper extracted from its sample page when it was scaffolded
(2026-11-18). After improving the parser, check the new values and update EXPECTED."""
from vehicle_scraper.sites.base import Listing
from vehicle_scraper.sites.cars24 import Cars24Scraper

from .conftest import FakeClient

URL = 'https://www.cars24.com/buy-used-hyundai-verna-2018-cars-bulandshahar-25238979175/'
EXPECTED = {
    'source_site': 'cars24',
    'source_url': 'https://www.cars24.com/buy-used-hyundai-verna-2018-cars-bulandshahar-25238979175/',
    'listing_id': '25238979175',
    'price': 450000.0,
    'currency': 'INR',
    'mileage_km': 94848,
    'vehicle_type': 'Sedan',
    'make': 'Hyundai',
    'model': 'Verna',
    'model_year': 2018,
    'body_style': 'Sedan',
    'engine_displacement_l': 1.6,          # from the title "2018 Hyundai Verna 1.6 VTVT SX"
    'fuel_type': 'CNG',
    'transmission_type': 'Manual',
    'abs': True,
    'alloy_wheels': True,
    'navigation': True,
}


def test_cars24_detail(cfg):
    client = FakeClient({'/buy-used-hyundai-verna-2018-cars-bulandshahar-25238979175/': "cars24_detail.html"})
    rec = Cars24Scraper(cfg, client=client).parse(Listing('25238979175', URL))
    got = {k: v for k, v in rec.model_dump(exclude={"scraped_at", "parse_warnings"}).items() if v is not None}
    assert got == EXPECTED
    assert rec.parse_warnings == []
