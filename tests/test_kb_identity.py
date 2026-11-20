"""Identity rules (offline): model/trim splitting, display names, spelling similarity."""
from collections import Counter

import pytest

pytest.importorskip("psycopg")

from vehicle_scraper.kb.db import compact_key
from vehicle_scraper.kb.identity import display_name, load_seed, similar, split_model, split_trim


@pytest.mark.parametrize("raw, name, attrs", [
    ("RAV4 HYBRID 4X4", "RAV4", {"fuel_type": "Hybrid", "drivetrain": "4WD"}),
    ("LAND CRUISER PRADO 4X4", "LAND CRUISER PRADO", {"drivetrain": "4WD"}),
    ("FORTUNER 4X4", "FORTUNER", {"drivetrain": "4WD"}),
    ("New Corolla", "Corolla", {}),
    ("Corolla Cross", "Corolla Cross", {}),
    ("Land Cruiser 200", "Land Cruiser 200", {}),          # the generation stays: AI/human decide
    ("4X4", "4X4", {"drivetrain": "4WD"}),                 # never empties a name
])
def test_split_model(raw, name, attrs):
    assert split_model(raw) == (name, attrs)


def test_spellings_share_a_key():
    assert compact_key("Rav 4") == compact_key("RAV4") == compact_key("rav-4") == compact_key(split_model("RAV4 HYBRID 4X4")[0])
    assert compact_key("Citroën") == compact_key("CITROEN")


@pytest.mark.parametrize("raw, label", [
    ("2.8 DC 4x4 Diésel", None),                 # only attributes: no trim label
    ("1.8 FWD LS Mecanica", "LS"),
    ("2.4 SRV Automatica 4x4 Diesel", "SRV"),
    ("Grand Touring 2.5 Suv Automatica 4x4", "Grand Touring"),
    ("Zenith 1.25 Hatchback Manual", "Zenith"),
    ("Cool 1.4 Aire Acondicionado", "Cool"),
    ("Advance CVT", "Advance"),
    ("4x2 Estacas", None),
    ("GR-S", "GR-S"),
])
def test_split_trim(raw, label):
    assert split_trim(raw) == label


def test_display_name_prefers_mixed_case_then_titlecases():
    assert display_name(Counter({"Rav 4": 98, "Rav4": 36, "RAV4": 12})) == "Rav 4"
    assert display_name(Counter({"LAND CRUISER PRADO": 4})) == "Land Cruiser Prado"
    assert display_name(Counter({"T-CROSS": 3})) == "T-Cross"
    assert display_name(Counter({"CX-30": 3, "GTI": 1})) == "CX-30"


def test_similar_is_spelling_only():
    assert similar("Corola", "Corolla")
    assert not similar("Prado", "Land Cruiser Prado")      # a different name -> individual review


def test_seed_has_unique_keys():
    seen = {}
    for m in load_seed():
        for alias in [m["name"], *(m.get("aliases") or [])]:
            key = compact_key(alias)
            assert key not in seen, f"{alias} clashes with {seen[key]}"
            seen[key] = m["name"]
        assert m.get("class", "car") in ("car", "motorcycle", "heavy")
