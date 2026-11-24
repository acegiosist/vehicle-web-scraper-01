"""Offline: token splitting of model/trim names, spelling keys, the make list."""
from __future__ import annotations

from collections import Counter

import pytest

from vehicle_scraper.kb.identity import (EXCLUDED_CLASSES, compact_key, display_name, load_seed,
                                         split_number, split_tokens)


@pytest.mark.parametrize("trim, label, attrs", [
    ("Touring 2.0 Suv Automatico 4x2", "Touring",
     {"engine_displacement_l": 2.0, "body_style": "SUV", "transmission_type": "Automatic", "drivetrain": "2WD"}),
    ("1.8 LS Mecanica", "LS", {"engine_displacement_l": 1.8, "transmission_type": "Manual"}),
    ("2.8 DC 4x4 Diésel", None,
     {"engine_displacement_l": 2.8, "body_style": "Pickup", "drivetrain": "4WD", "fuel_type": "Diesel"}),
    ("Pick Up Doble Cabina 4x4", None, {"body_style": "Pickup", "drivetrain": "4WD"}),
    ("LTZ 1.4 Turbo Full Equipo 5 Puertas", "LTZ", {"engine_displacement_l": 1.4, "turbo": True, "doors": 5}),
    ("GLS 16V A/A DH", "GLS", {}),
    ("XLT SuperCrew", "XLT", {"body_style": "Pickup"}),
    ("EX-L", "EX-L", {}),
    ("Limited", "Limited", {}),
    ("2.0 1.8 Aut", None, {"engine_displacement_l": 2.0, "transmission_type": "Automatic"}),   # first wins
])
def test_split_trim(trim, label, attrs):
    assert split_tokens(trim) == (label, attrs)


@pytest.mark.parametrize("model, name, attrs", [
    ("RAV4 HYBRID 4X4", "RAV4", {"fuel_type": "Hybrid", "drivetrain": "4WD"}),
    ("Luv 2.3", "Luv", {"engine_displacement_l": 2.3}),
    ("Wagon R 1.0", "Wagon R", {"engine_displacement_l": 1.0}),       # "Wagon" stays in a model name
    ("Land Cruiser Prado VX 4X4", "Land Cruiser Prado VX", {"drivetrain": "4WD"}),
    ("Sport", "Sport", {}),
    ("1.3", None, {"engine_displacement_l": 1.3}),                      # nothing but attributes
    ("5.2 V8", None, {"engine_displacement_l": 5.2, "engine_cylinders": 8}),
    ("CX-30", "CX-30", {}),
    ("1500", "1500", {}),                                               # Ram 1500, Mazda 3, Porsche 911
    ("3", "3", {}),
    ("Flex", "Flex", {}),                                               # Ford Flex: the word is the model
    ("Hybrid", "Hybrid", {}),
])
def test_split_model(model, name, attrs):
    assert split_tokens(model, model=True) == (name, attrs)


def test_moto_numbers_stay_in_the_name():
    assert split_tokens("SF 150 FI", moto=True) == ("SF 150 FI", {})
    assert split_tokens("390 NG", moto=True) == ("390 NG", {})


def test_split_number():
    assert split_number("150 Bus") == ("150", "Bus")
    assert split_number("452") == ("452", None)
    assert split_number("LS 150") == (None, "LS 150")


def test_keys_and_display_names():
    assert compact_key("Rav 4") == compact_key("RAV4") == compact_key("rav-4") == "rav4"
    assert compact_key("Citroën") == "citroen"
    assert display_name(Counter({"KICKS": 5, "Kicks": 2})) == "Kicks"
    assert display_name(Counter({"LAND CRUISER": 3})) == "Land Cruiser"
    assert display_name(Counter({"CX-30": 1})) == "CX-30"


def test_seed_is_valid_and_covers_scope_rules():
    seed = load_seed()
    names = {m["name"]: m for m in seed["makes"]}
    assert names["Toyota"]["class"] == "car" and names["Yamaha"]["class"] == "motorcycle"
    assert names["Kenworth"]["class"] == "heavy" and names["Komatsu"]["class"] == "machinery"
    assert {m["class"] for m in seed["makes"]} <= {"car", "motorcycle", *EXCLUDED_CLASSES}
    keys = Counter(compact_key(s) for m in seed["makes"] for s in [m["name"], *(m.get("aliases") or [])])
    assert not [k for k, n in keys.items() if n > 1]


def test_seed_rejects_unknown_class(tmp_path):
    p = tmp_path / "makes.yaml"
    p.write_text("makes:\n  - {name: X, class: spaceship}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown class"):
        load_seed(p)
