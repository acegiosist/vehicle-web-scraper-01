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
    assert N.to_displacement_l("1.5 L (1.496 cc)") == 1.5   # explicit litres win over "cc"
    assert N.to_displacement_l("SKYACTIV-G 2,0L / 16 Válvulas") == 2.0
    assert N.to_displacement_l("4 cilindros en línea, 16 válvulas") is None


def test_displacement_motorcycle():
    assert N.to_displacement_l("125") is None                # 0.125 L: not a car engine
    assert N.to_displacement_l("125", moto=True) == 0.125    # exact cc kept
    assert N.to_displacement_l("155 cc", moto=True) == 0.155
    assert N.to_displacement_l("1.802 cc", moto=True) == 1.802
    assert N.to_displacement_l("30 cc", moto=True) is None


def test_displacement_from_title():
    assert N.displacement_from_title("Sail 1.4 LS Mecanico") == "1.4"
    assert N.displacement_from_title("Duster Oroch 1.3T Intens") == "1.3"
    assert N.displacement_from_title("Ecosport 2,0L 16v") == "2,0"
    assert N.displacement_from_title("Clase C 63 AMG") is None
    assert N.displacement_from_title("Ioniq 5 77.4 kWh") is None
    assert N.displacement_from_title("5.000 km") is None


def test_cylinders_words():
    assert N.to_cylinders("cuatro en línea") == 4
    assert N.to_cylinders("seis en V") == 6
    assert N.to_cylinders("4 en línea") == 4


def test_power_units():
    assert N.to_hp("175/6000") == 175
    assert N.to_hp("150 kW") == 201
    assert N.to_hp("200", "Potencia (CV)") == 197
    assert N.to_hp("200 hp / 149 kW") == 200                 # the number's own unit wins
    assert N.to_hp("149 kW (200 hp)") == 200


def test_power_motorcycle():
    assert N.to_hp("10Hp (7.5Kw) @ 8000 rpm", moto=True) == 10   # not 10 x 1.34
    assert N.to_hp("13,8 HP @ 9000 RPM", moto=True) == 14
    assert N.to_hp("13,8 HP @ 9000 RPM") is None                  # cars: below 30 hp
    assert N.to_hp("1 HP", moto=True) is None


def test_rim_from_tire_text():
    assert N.rim_from_tire_text("R16") == 16
    assert N.rim_from_tire_text('16" x 6,5J Aluminio') == 16
    assert N.rim_from_tire_text("13 x 4.5J") == 13
    assert N.rim_from_tire_text("Llantas en aluminio de 16¿") == 16
    assert N.rim_from_tire_text("14") is None                 # bare: could be a width or profile
    assert N.rim_from_tire_text("7.50 x 16 12PR") is None     # truck tire size, not a rim


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
    assert N.to_drivetrain("4x2") == "2WD"             # front/rear not stated -> never guessed
    assert N.to_drivetrain("2WD") == "2WD"
    assert N.to_drivetrain("4x2 delantera") == "FWD"
    assert N.to_drivetrain("Doble") == "4WD"               # "Tracción: Doble"
    assert N.to_drivetrain("Doble cabina") is None
    assert N.to_body("Vans") == "Van"
    assert N.to_body("Carga") == "Van" and N.to_body("Pasajeros") == "Van"
    assert N.to_body("Camión de carga") == "Truck"
    assert N.to_body("Deportivo") is None                  # fallback only, see test_mapping
    assert N.body_fallback("Deportivo") == "Coupe"
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
    # Motorcycle "Motor" descriptions: the stroke/cylinder count is not 4.0 L (or 1.0 L).
    assert N.to_displacement_l("4 TIEMPOS, MONOCILÍNDRICO", "Motor", moto=True) is None
    assert N.to_displacement_l("4 tiempos, 1 cilindro enfriado por aire", "Motor", moto=True) is None
    assert N.to_displacement_l("4-stroke single cylinder", "Engine", moto=True) is None
    assert N.to_displacement_l("4 tiempos 124 cc", "Motor", moto=True) == 0.124


def test_fuel_gas_and_mixed():
    assert N.to_fuel("Gas natural vehicular") == "CNG"  # never Gasoline
    assert N.to_fuel("GNV") == "CNG"
    assert N.to_fuel("CNG") == "CNG"
    assert N.to_fuel("GLP") is None                     # LPG: no schema value
    assert N.to_fuel("Gasolina y gas") is None          # bi-fuel
    assert N.to_fuel("Gasolina y GNV") is None          # bi-fuel
    assert N.to_fuel("Petrol + CNG") is None            # bi-fuel
    assert N.to_fuel("Gas") == "Gasoline"               # US English "gas"
    assert N.to_fuel("Flex") == "Flex" and N.to_fuel("Flex Fuel") == "Flex"
    assert N.to_fuel("Gasolina/Etanol") == "Flex" and N.to_fuel("E85") == "Flex"
    assert N.to_fuel("Flex Hybrid") == "Hybrid"         # a hybrid first


def test_us_cab_styles_are_pickups():
    for cab in ("Crew Cab", "Extended Cab", "Regular Cab", "SuperCrew", "Super Cab", "Chassis Cab",
                "Double Cab", "Quad Cab", "Cabina extendida"):
        assert N.to_body(cab) == "Pickup", cab
        assert N.body_from_title(f"Lariat {cab}") == "Pickup", cab
    assert N.body_from_title("Cabriolet") == "Convertible"   # "cab" alone is not a cab style
    assert N.to_body("Cab") is None
    assert N.to_fuel("Gasolina y eléctrico") == "Hybrid"
    assert N.to_fuel("Diesel - Eléctrico") == "Hybrid"
    assert N.to_fuel("Eléctrico") == "EV"
    assert N.to_fuel("Gasolina - inyección electrónica") == "Gasoline"


@pytest.mark.parametrize("raw,iso", [
    ("2026-11-14T20:40:46.000Z", "2026-11-14T20:40:46+00:00"),        # carroya search
    ("2026-11-19T21:41:39.000+0000", "2026-11-19T21:41:39+00:00"),    # carroya detail
    ("2026-10-02T07:45:00+00:00", "2026-10-02T07:45:00+00:00"),       # truecar listedAt
    ("2026-10-02T02:45:00-05:00", "2026-10-02T07:45:00+00:00"),
    ("2026-09-19", "2026-09-19T00:00:00+00:00"),                      # sitemap lastmod
])
def test_to_datetime(raw, iso):
    assert N.to_datetime(raw).isoformat() == iso


@pytest.mark.parametrize("raw", [None, "", "hace 3 días", 20261114, "2026-13-01"])
def test_to_datetime_unparseable(raw):
    assert N.to_datetime(raw) is None
