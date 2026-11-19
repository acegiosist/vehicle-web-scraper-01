import pytest

from vehicle_scraper.catalog.canonical import (MakeTable, display_case, model_key, parse_names,
                                               split_known_prefix)

MAKES = MakeTable({"Jeep": {}, "Land Rover": {"aliases": ["Landrover"]}, "Mercedes-Benz": {"aliases": ["Mercedes Benz"]},
                   "Maruti Suzuki": {"aliases": ["Maruti"]}, "Toyota": {}, "Sinotruk": {"class": "heavy"}})


def test_make_aliases_and_case():
    assert MAKES.resolve("JEEP").name == "Jeep" and MAKES.resolve("jeep").in_seed
    assert MAKES.resolve("Landrover").slug == "land-rover"
    assert MAKES.resolve("Maruti").name == "Maruti Suzuki"
    assert MAKES.resolve("Sinotruk").heavy
    unknown = MAKES.resolve("ZHONGTONG")
    assert unknown.name == "Zhongtong" and not unknown.in_seed


@pytest.mark.parametrize("raw,trim,attrs", [
    ("Limited 2.4 Automatica", "Limited", {"engine_displacement_l": 2.4, "transmission_type": "Automatic"}),
    ("1.8 XEi-L Automatico", "XEi-L", {"engine_displacement_l": 1.8, "transmission_type": "Automatic"}),
    ("Grand Touring 2.5 Suv Automatica 4x2", "Grand Touring", {"body_style": "SUV", "drivetrain": "2WD"}),
    ("Alize 1.4 Mecanico Aire Acondicionado", "Alize", {"transmission_type": "Manual"}),
    ("2.5 4x2 Doble Cabina Pro-D Diesel", "Pro-D", {"fuel_type": "Diesel", "body_style": "Pickup"}),
    ("1.6 5 Puertas Mecanico", "", {"doors": 5}),
    ("Intens 1.3T CVT", "Intens", {"engine_displacement_l": 1.3, "transmission_type": "CVT"}),
    ("GS EV", "GS", {"fuel_type": "EV"}),
    ("ltz", "LTZ", {}),
])
def test_trim_cleaning(raw, trim, attrs):
    p = parse_names("Toyota", "Corolla", raw, MAKES)
    assert p.trim_text == trim
    assert attrs.items() <= p.attrs.items()


def test_model_cleaning_and_keys():
    p = parse_names("JEEP", "COMPASS 4X4", None, MAKES)
    assert p.model_text == "COMPASS" and p.attrs["drivetrain"] == "4WD"
    assert parse_names("Maruti", "Wagon R 1.0", None, MAKES).attrs["engine_displacement_l"] == 1.0
    assert model_key("Rav 4") == model_key("RAV4") == "rav4"
    assert model_key("Clase C") == model_key("C Class") == "c"
    assert model_key("Serie 3") == model_key("3 SERIES") == "3"
    assert parse_names("Toyota", "Corolla", "Corolla XEi 1.8 AT", MAKES).trim_text == "XEi"


def test_known_prefix_split_is_conservative():
    assert split_known_prefix("TAHOE LTZ", {"tahoe"}) == ("TAHOE", "LTZ")
    assert split_known_prefix("COROLLA CROSS", {"corolla"}) == ("COROLLA", "CROSS")   # why the full key is checked first
    p = parse_names("Toyota", "COROLLA CROSS", None, MAKES, known_models={"corolla", "corollacross"})
    assert p.model_text == "COROLLA CROSS" and not p.model_split
    p = parse_names("Toyota", "FORTUNER SRV 4X4", None, MAKES, known_models={"fortuner"})
    assert (p.model_text, p.trim_text, p.model_split) == ("FORTUNER", "SRV", True)


def test_display_case():
    assert display_case("T-CROSS") == "T-Cross"
    assert display_case("x-trail") == "X-Trail"
    assert display_case("XEi-L 320i Grand i10") == "XEi-L 320i Grand i10"
    assert display_case("EDICION DE LUJO") == "Edicion de Lujo"
