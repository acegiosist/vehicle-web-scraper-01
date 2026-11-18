"""Snapshot of what the truecar scraper extracted from its sample page when it was scaffolded
(2026-11-18). After improving the parser, check the new values and update EXPECTED."""
from vehicle_scraper.sites.base import Listing
from vehicle_scraper.sites.truecar import TruecarScraper

from .conftest import FakeClient

URL = 'https://www.truecar.com/used-cars-for-sale/listing/19UDE4G77TA007881/2026-acura-integra/'
EXPECTED = {
    'source_site': 'truecar',
    'source_url': 'https://www.truecar.com/used-cars-for-sale/listing/19UDE4G77TA007881/2026-acura-integra/',
    'listing_id': '19UDE4G77TA007881',
    'price': 34662.0,
    'currency': 'USD',
    'mileage_km': 9820,
    'vehicle_type': 'Hatchback',
    'make': 'Acura',
    'model': 'Integra',
    'model_year': 2026,
    'body_style': 'Hatchback',
    'engine_displacement_l': 1.5,
    'engine_cylinders': 4,
    'horsepower_hp': 200,
    'fuel_type': 'Gasoline',
    'fuel_tank_capacity_l': 12.4,
    'transmission_type': 'Manual',
    'drivetrain': 'FWD',
    'seats': 5,
    'cargo_capacity_l': 688,
    'wheel_size_in': 18,
    'tire_size': '235/40R18',
    'fuel_economy_kml': 26.0,
    'stability_control': True,
    'traction_control': True,
    'adaptive_cruise_control': True,
    'lane_assist': True,
    'blind_spot_monitoring': True,
    'sunroof': True,
    'alloy_wheels': True,
    'heated_seats': True,
    'memory_seats': True,
    'climate_control': True,
    'dual_zone_ac': True,
    'keyless_entry': True,
    'screen_size_in': 9.0,
    'bluetooth': True,
    'apple_carplay': True,
    'android_auto': True,
    'reverse_camera': True,
    'parking_sensors': True,
    'alarm': True,
}


def test_truecar_detail(cfg):
    client = FakeClient({'/used-cars-for-sale/listing/19UDE4G77TA007881/2026-acura-integra/': "truecar_detail.html"})
    rec = TruecarScraper(cfg, client=client).parse(Listing('19UDE4G77TA007881', URL))
    got = {k: v for k, v in rec.model_dump(exclude={"scraped_at", "parse_warnings"}).items() if v is not None}
    assert got == EXPECTED
