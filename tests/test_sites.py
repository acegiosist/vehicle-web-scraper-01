"""Site parsers against fixtures captured from the real pages/API (Nov 2026)."""
import json

from vehicle_scraper.config import Settings
from vehicle_scraper.extract import detect_block
from vehicle_scraper.sites.base import Listing
from vehicle_scraper.sites.carroya import CarroYaScraper
from vehicle_scraper.sites.cofino import CofinoScraper

from .conftest import FIXTURES, FakeClient


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


def _carroya_variant(tmp_path, cylindrical, sheet_cc="2656", category=None, version=None):
    """The Tucson fixture with the seller-typed displacement (``cylindrical`` and its copy in
    main-features) and the technical sheet's "Cilindrada (c.c³)" replaced."""
    data = json.loads((FIXTURES / "carroya_detail.json").read_text(encoding="utf-8"))
    d = data.get("data", data)
    d["cylindrical"] = cylindrical
    if category:
        d["category"] = category
    if version is not None:
        d["version"] = version
    for f in d["main-features"]:
        if f["name"] == "Engine Displacement":
            f["description"] = str(cylindrical)
    for g in d["technical_sheet"]:
        g["specifications"] = [s for s in g["specifications"] if s["name"] != "Cilindrada (c.c³)"]
    if sheet_cc:
        d["technical_sheet"][0]["specifications"].append({"name": "Cilindrada (c.c³)", "value": sheet_cc})
    p = tmp_path / "carroya_variant.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    s = CarroYaScraper(Settings(data_dir=tmp_path, request_delay_s=0), client=FakeClient({"find-vehicle-detail": str(p)}))
    return s.parse(Listing("928d091b-9e37-4938-a3f3-a091dc538590", "x"))


def test_carroya_box_zero_is_not_filled_in(tmp_path):
    # "box": "0" means the seller left the gearbox blank: no value from it and no warning.
    data = json.loads((FIXTURES / "carroya_detail.json").read_text(encoding="utf-8"))
    data.get("data", data)["box"] = "0"
    p = tmp_path / "carroya_box.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    s = CarroYaScraper(Settings(data_dir=tmp_path, request_delay_s=0), client=FakeClient({"find-vehicle-detail": str(p)}))
    rec = s.parse(Listing("928d091b-9e37-4938-a3f3-a091dc538590", "x"))
    assert not [w for w in rec.parse_warnings if "transmission_type" in w]


def _disp_warnings(rec):
    return [w for w in rec.parse_warnings if "engine_displacement_l" in w]


def test_carroya_rounded_cylindrical_does_not_beat_technical_sheet(tmp_path):
    # Chevrolet Tracker 1.8: the seller typed "2"; the technical sheet says 1796 cc.
    rec = _carroya_variant(tmp_path, 2, sheet_cc="1796")
    assert rec.engine_displacement_l == 1.8
    assert _disp_warnings(rec) == []                     # the size is known, so no noise


def test_carroya_rounded_cylindrical_alone_stays_null(tmp_path):
    rec = _carroya_variant(tmp_path, 4, sheet_cc=None, version="Full Equipo")   # no "d.d" in the title
    assert rec.engine_displacement_l is None                 # "4" is not 4.0 L
    assert _disp_warnings(rec) == ["could not parse engine_displacement_l from '4'"]


def test_carroya_moto_rounded_cylindrical_is_not_four_litres(tmp_path):
    # BMW R1250 GS: "cylindrical": 4 (and the same "4" under main-features).
    rec = _carroya_variant(tmp_path, 4, sheet_cc=None, category="Motos", version="GS")
    assert rec.vehicle_type == "Motorcycle"
    assert rec.engine_displacement_l is None


def test_carroya_cc_with_extra_digit_falls_back_to_sheet(tmp_path):
    # Chevrolet Sonic 1.6: "cylindrical": 16000; technical sheet 1600.
    rec = _carroya_variant(tmp_path, 16000, sheet_cc="1600")
    assert rec.engine_displacement_l == 1.6
    assert _disp_warnings(rec) == []


def test_carroya_plausible_cylindrical_still_used(tmp_path):
    assert _carroya_variant(tmp_path, 16, sheet_cc=None).engine_displacement_l == 1.6     # tenths of a litre
    assert _carroya_variant(tmp_path, 2000, sheet_cc=None).engine_displacement_l == 2.0   # cc
