"""Headlight type, brakes per axle and wireless charger: parsers, labels and equipment lists."""
import pytest

from vehicle_scraper import normalize as N
from vehicle_scraper.mapping import RecordBuilder, match_equipment, match_features, match_label


@pytest.mark.parametrize("text, kind", [
    ("LED", "LED"), ("Full LED", "LED"), ("Xenón", "Xenon"), ("Bi-xenon", "Xenon"), ("HID", "Xenon"),
    ("Halógenos", "Halogen"), ("LED matricial", "MatrixLED"), ("Matrix LED", "MatrixLED"),
    ("Sí", None), ("Proyectores", None),
])
def test_to_headlight(text, kind):
    assert N.to_headlight(text) == kind


@pytest.mark.parametrize("text, kind", [
    ("Disco", "Disc"), ("Discos ventilados", "Disc"), ("Disc", "Disc"), ("Tambor", "Drum"), ("Drum", "Drum"),
    ("Disco/Tambor", None), ("Sí", None),
])
def test_to_brake(text, kind):
    assert N.to_brake(text) == kind


@pytest.mark.parametrize("text, expected", [
    ("4-Wheel Disc Brakes", {"brake_front": "Disc", "brake_rear": "Disc"}),
    ("Frenos de disco en las 4 ruedas", {"brake_front": "Disc", "brake_rear": "Disc"}),
    ("Front Disc/Rear Drum Brakes", {"brake_front": "Disc", "brake_rear": "Drum"}),
    ("Frenos de disco delanteros y de tambor traseros", {"brake_front": "Disc", "brake_rear": "Drum"}),
    ("Frenos delanteros de disco ventilado", {"brake_front": "Disc"}),
    ("Frenos ABS", {}),
    ("Asistente de frenado de emergencia", {}),
    ("Freno de mano electrónico", {}),
    ("LED Headlights", {"headlight_type": "LED"}),
    ("Faros de xenón", {"headlight_type": "Xenon"}),
    ("Faros full LED matriciales", {"headlight_type": "MatrixLED"}),
    ("Faros antiniebla LED", {}),                     # fog lights are not the headlights
    ("LED Tail Lights", {}),
    ("Luces diurnas LED", {}),
    ("Headlights-Auto-Leveling", {}),
    ("Sin faros LED", {}),                            # negated
])
def test_match_equipment(text, expected):
    assert match_equipment(text) == expected


@pytest.mark.parametrize("text", ["Wireless Charging", "Wireless Phone Charging", "Cargador inalámbrico",
                                  "Carga inalámbrica para celular", "Cargador de celular inalámbrico"])
def test_wireless_charger_feature(text):
    assert "wireless_charger" in match_features(text)


def test_wireless_charger_negated():
    assert "wireless_charger" not in match_features("Sin cargador inalámbrico")


@pytest.mark.parametrize("label, field", [
    ("Frenos delanteros", "brake_front"), ("Frenos traseros", "brake_rear"), ("Front Brakes", "brake_front"),
    ("Tipo de faros", "headlight_type"), ("Headlamp Type", "headlight_type"), ("Faros delanteros", "headlight_type"),
    ("Freno de mano", None), ("Control de frenos ABS", None), ("Faros antiniebla", None),
    ("Front Brake Rotor Diameter", None), ("Rear Brake Width", None),
    ("Auto On/Off Headlights", None),
])
def test_labels(label, field):
    assert match_label(label) == field


def test_builder_pairs_and_lists():
    b = RecordBuilder("s", "u", "1")
    b.add_pair("Frenos delanteros", "Disco ventilado")
    b.add_pair("Frenos traseros", "Tambor")
    b.add_pair("Faros delanteros", "Sí")                   # a yes/no says nothing about the type
    b.add_pair("Frenos de disco en las 4 ruedas", "S")     # a boolean label: front is already set
    b.add_feature_list(["Faros de xenón", "Cargador inalámbrico"])
    rec = b.build()
    assert (rec.brake_front, rec.brake_rear, rec.headlight_type, rec.wireless_charger) == ("Disc", "Drum", "Xenon", True)
    assert not [w for w in rec.parse_warnings if "headlight" in w or "brake" in w]
