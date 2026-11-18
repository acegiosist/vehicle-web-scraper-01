import pytest

from vehicle_scraper import normalize as N


@pytest.mark.parametrize("raw,expected", [
    ("27,770 km", 27770), ("44.900.000", 44900000), ("2.700", 2700), ("1.5l", 1.5),
    ("14,5 km/l", 14.5), ("9,102858", 9.102858), ("1.234,5", 1234.5), ("1,234.5", 1234.5),
    ("$169,420", 169420), ("abc", None), (None, None),
])
def test_parse_number(raw, expected):
    assert N.parse_number(raw) == expected


def test_displacement():
    assert N.to_displacement_l("2656", "Cilindrada (c.c)") == 2.7
    assert N.to_displacement_l("1.5l") == 1.5
    assert N.to_displacement_l("2.700") == 2.7          # Colombian "cilindraje 2.700"
    assert N.to_displacement_l("1998 cc") == 2.0


def test_power_units():
    assert N.to_hp("175/6000") == 175
    assert N.to_hp("150 kW") == 201
    assert N.to_hp("200", "Potencia (CV)") == 197


def test_volume_and_economy():
    assert N.to_liters("17.2", "Capacidad del tanque (Galones)") == 65.1
    assert N.to_liters("38 cu ft") == 1076.0
    assert N.to_kml("30 mpg") == 12.8
    assert N.to_kml("6.5 l/100km") == 15.4
    assert N.to_kml("14,5 km/l") == 14.5


def test_enums():
    assert N.to_transmission("Automática") == "Automatic"
    assert N.to_transmission("Mecánica") == "Manual"
    assert N.to_transmission("CVT") == "CVT"
    assert N.to_drivetrain("4x4") == "4WD"
    assert N.to_drivetrain("Tracción integral") == "AWD"
    assert N.to_drivetrain("4x2") is None              # ambiguous -> never guessed
    assert N.to_fuel("Gasolina") == "Gasoline"
    assert N.to_fuel("Híbrido") == "Hybrid"
    assert N.to_fuel("Eléctrico") == "EV"
    assert N.to_fuel("ACPM") == "Diesel"
    assert N.to_body("Camioneta") == "SUV"
    assert N.to_body("Pick-up doble cabina") == "Pickup"
    assert N.to_country("Japón") == "Japan"


def test_booleans():
    assert N.to_bool("S") is True and N.to_bool("Sí") is True and N.to_bool("✓") is True
    assert N.to_bool("N") is False and N.to_bool("No disponible") is False
    assert N.to_bool("Aleación") is None


def test_tires_and_rims():
    assert N.to_tire_size("225/65 R17") == "225/65R17"
    assert N.to_tire_size("235/60") == "235/60"
    assert N.to_inches("R16") == 16


def test_displacement_ignores_cylinder_and_valve_tokens():
    assert N.to_displacement_l("V6 3.5", "Motor") == 3.5
    assert N.to_displacement_l("3.5 V6") == 3.5
    assert N.to_displacement_l("2.0 16V") == 2.0
    assert N.to_displacement_l("4 cilindros 1.6") == 1.6
    assert N.to_displacement_l("1.6 V") == 1.6
    assert N.to_displacement_l("L4 1.5") == 1.5
    assert N.to_displacement_l(2656, "cc") == 2.7


def test_fuel_gas_and_mixed():
    assert N.to_fuel("Gas natural vehicular") is None   # CNG: no schema value, never Gasoline
    assert N.to_fuel("GNV") is None
    assert N.to_fuel("Gasolina y gas") is None          # bi-fuel
    assert N.to_fuel("Gas") == "Gasoline"               # US English "gas"
    assert N.to_fuel("Gasolina y eléctrico") == "Hybrid"
    assert N.to_fuel("Diesel - Eléctrico") == "Hybrid"
    assert N.to_fuel("Eléctrico") == "EV"
    assert N.to_fuel("Gasolina - inyección electrónica") == "Gasoline"
