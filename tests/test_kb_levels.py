"""Offline: level field lists vs migration 0006, and the build's pure rules."""
from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

from vehicle_scraper.kb import build as B
from vehicle_scraper.kb import levels
from vehicle_scraper.models import BOOLEAN_FIELDS, FEATURE_FIELDS

MIGRATION = (Path(__file__).resolve().parents[1] / "src" / "vehicle_scraper" / "kb" / "migrations" / "versions"
             / "0006_three_levels.py").read_text(encoding="utf-8")


def _frozen_list(name: str) -> list[str]:
    for node in ast.walk(ast.parse(MIGRATION)):
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == name:
            return ast.literal_eval(node.value)
    raise AssertionError(name)


def test_migration_feature_columns_match_models():
    # models.py gaining an equipment field fails here until a migration adds its column.
    bools = set(_frozen_list("FEATURE_BOOLS"))
    for f in FEATURE_FIELDS:
        column = levels.COLUMN_OF.get(f, f)
        assert column in bools or f"    {column} " in MIGRATION, f
    assert set(BOOLEAN_FIELDS) - bools == {"wireless_charger"}          # its own column in 0006


def test_every_level_column_exists_in_the_migration():
    bools = set(_frozen_list("FEATURE_BOOLS"))              # generated as "<name> boolean"
    for column in levels.GENERATION_COLUMNS + levels.POWERTRAIN_COLUMNS + levels.VARIANT_COLUMNS:
        assert column in bools or f"    {column} " in MIGRATION, column


def test_field_placement():
    assert {levels.COLUMN_OF.get(f, f) for f in FEATURE_FIELDS} <= set(levels.VARIANT_FROM_LISTINGS)
    assert {"headlight_type_code", "brake_front_code", "brake_rear_code", "wireless_charger"} \
        <= set(levels.VARIANT_COLUMNS)
    assert len(levels.VARIANT_COLUMNS) == len(set(levels.VARIANT_COLUMNS))
    assert {"doors", "seats", "cargo_capacity_l", "fuel_tank_capacity_l"} == set(levels.GENERATION_FROM_LISTINGS)
    assert "country_of_manufacture" in levels.VARIANT_COLUMNS and "seats" in levels.VARIANT_COLUMNS
    assert levels.SOURCE_RANK["manual"] < levels.SOURCE_RANK["external"] < levels.SOURCE_RANK["listings"] \
        < levels.SOURCE_RANK["ai"]


def test_compatible_keys():
    pt = {"fuel": "Gasoline", "trans": "CVT", "drive": "FWD", "disp": 1.6, "cyl": None}
    assert B._compatible(("Gasoline", "Automatic", None, 1.6, None), pt)       # Automatic ~ CVT, no drive
    assert B._compatible(("Gasoline", None, "2WD", 1.62, None), pt)            # 2WD ~ FWD, 0.02 L apart
    assert not B._compatible(("Gasoline", "CVT", "FWD", 2.0, None), pt)
    assert not B._compatible(("Diesel", "CVT", "FWD", 1.6, None), pt)
    assert not B._compatible(("Gasoline", "Manual", "FWD", 1.6, None), pt)
    assert B.match_key(("Gasoline", "Automatic", "AWD", None, 4)) == "Gasoline|Automatic|AWD||4"


def test_mechanical_and_equipment_rules():
    one = B._mechanical([150])
    assert (one["value"], one["status"], one["disagree"]) == (150, "accepted", False)   # one listing is enough
    spread = B._mechanical([150, 150, 190])
    assert spread["value"] == 150 and spread["disagree"]                                 # > 10 % apart
    assert B._equipment([True])["status"] == "pending"                                   # needs 2
    assert B._equipment([True, True, False])["status"] == "pending"                      # 67 % < 70 %
    ok = B._equipment([True, True, True, False])
    assert (ok["value"], ok["status"], ok["agreement"]) == (True, "accepted", 0.75)


def test_split_year_needs_disjoint_engines():
    years = {2016: Counter({"1.6": 5}), 2018: Counter({"1.6": 4}), 2020: Counter({"1.5": 6}), 2022: Counter({"1.5": 3})}
    year, before, after = B._split_year(years)
    assert year == 2020 and before == {"1.6": 9} and after == {"1.5": 9}
    assert B._split_year({2016: Counter({"1.6": 5}), 2020: Counter({"1.6": 3, "2.0": 3})}) is None


def test_evolution_needs_agreement_on_both_sides():
    by_year = {2024: Counter({False: 3}), 2025: Counter({False: 2}), 2026: Counter({True: 3})}
    assert B._evolution(by_year) == (2026, False, True, 5, 3)
    assert B._evolution({2024: Counter({False: 2, True: 1}), 2026: Counter({True: 3})}) is None
