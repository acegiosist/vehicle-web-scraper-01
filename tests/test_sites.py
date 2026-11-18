"""Site parsers against fixtures captured from the real pages/API (Nov 2026)."""
from vehicle_scraper.extract import detect_block
from vehicle_scraper.sites.base import Listing
from vehicle_scraper.sites.carroya import CarroYaScraper
from vehicle_scraper.sites.cofino import CofinoScraper

from .conftest import FakeClient


def test_cofino_detail(cfg):
    client = FakeClient({"/catalogo/": "cofino_detail.html"})
    s = CofinoScraper(cfg, client=client)
    url = "https://cofinousados.com/catalogo/honda-hr-v-exl-2022-6390"
    rec = s.parse(Listing("6390", url))
    assert rec.make == "Honda"
    assert rec.model == "HR-V EXL"
    assert rec.model_year == 2022
    assert rec.transmission_type == "Automatic"
    assert rec.fuel_type == "Gasoline"
    assert rec.engine_displacement_l == 1.5
    assert rec.mileage_km == 27770
    assert rec.drivetrain == "2WD"                      # 4x2: front/rear not stated
    assert rec.price == 169420 and rec.currency == "GTQ"  # site's JSON-LD wrongly says MXN
    assert rec.parse_warnings == []                     # MXN quirk is known, not warned


def test_carroya_detail(cfg):
    client = FakeClient({"find-vehicle-detail": "carroya_detail.json"})
    s = CarroYaScraper(cfg, client=client)
    rec = s.parse(Listing("928d091b-9e37-4938-a3f3-a091dc538590", "x"))
    assert (rec.make, rec.model, rec.trim, rec.model_year) == ("Hyundai", "Tucson", "2.7 4x4 Automatica Full Equipo", 2010)
    assert rec.engine_displacement_l == 2.7
    assert rec.engine_cylinders == 6
    assert rec.horsepower_hp == 175
    assert rec.fuel_type == "Gasoline"
    assert rec.fuel_tank_capacity_l == 65.1              # 17.2 US gallons
    assert rec.transmission_type == "Automatic"
    assert rec.drivetrain == "4WD"
    assert rec.cargo_capacity_l == 325
    assert rec.wheel_size_in == 16
    assert rec.tire_size == "235/60R16"
    assert rec.abs is True and rec.fog_lights is True and rec.alarm is True
    assert rec.alloy_wheels is True and rec.leather_seats is True
    assert rec.airbags_count == 2
    assert rec.vehicle_type == "SUV"                      # from "CARROCERIA WAGON" in the seller comments
    assert rec.mileage_km == 109000 and rec.currency == "COP"
    assert rec.source_url.endswith("/detalle/usado/hyundai/tucson/2010/bogota/928d091b-9e37-4938-a3f3-a091dc538590")
    assert rec.sunroof is None and rec.heated_seats is None   # not mentioned -> unknown


def test_block_detection():
    assert detect_block(403, "<script src='https://ct.captcha-delivery.com/c.js'></script>") == "DataDome CAPTCHA"
    assert detect_block(403, "<title>Attention Required! | Cloudflare</title>") == "Cloudflare challenge"
    assert detect_block(200, "", "https://www.mercadolibre.com.co/gz/account-verification?go=x") == \
        "Mercado Libre account verification"
    assert detect_block(200, "<html>ok</html>") is None
