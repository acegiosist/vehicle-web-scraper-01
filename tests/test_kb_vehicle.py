"""Offline: kb.vehicle_identity's frozen columns (migration 0016) vs kb/vehicle.py, final.py and levels.py."""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from vehicle_scraper.kb import final, levels, vehicle
from vehicle_scraper.models import BOOLEAN_FIELDS

MIGRATION = (Path(__file__).resolve().parents[1] / "src" / "vehicle_scraper" / "kb" / "migrations" / "versions"
             / "0016_vehicle_identity.py").read_text(encoding="utf-8")


def _frozen_bools() -> list[str]:
    for node in ast.walk(ast.parse(MIGRATION)):
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == "FEATURE_BOOLS":
            return ast.literal_eval(node.value)
    raise AssertionError("FEATURE_BOOLS")


def migration_columns() -> set[str]:
    body = MIGRATION.split("CREATE TABLE kb.vehicle_identity (", 1)[1].split("built_at", 1)[0]
    named = set(re.findall(r"^\s{4}([a-z_]+) [a-z]", body, flags=re.M))
    return named | set(_frozen_bools())


def test_migration_columns_match_sources():
    assert migration_columns() == set(vehicle.SOURCES)
    assert set(_frozen_bools()) == set(BOOLEAN_FIELDS)


def test_values_are_the_final_records_level_columns_without_the_listing():
    from_levels = {c for c, s in final.SOURCES.items() if s[0][:2] in ("g.", "p.", "v.")}
    assert set(vehicle.VALUES) == from_levels
    assert all(src.startswith(("g.", "p.", "v.")) for s in vehicle.VALUES.values() for src in s)
    assert vehicle.VALUES["seats"] == ["v.seats", "g.seats"]
    assert vehicle.VALUES["headlight_type"] == ["v.headlight_type_code"]


def test_every_published_level_column_has_a_column():
    # evidence is stored under the level column; sources and notes use this table's names
    published = set(levels.GENERATION_COLUMNS) | set(levels.POWERTRAIN_COLUMNS) | set(levels.VARIANT_COLUMNS)
    assert {levels.LISTING_FIELD_OF.get(c, c) for c in published} <= set(vehicle.VALUES)


def test_insert_sql_refuses_drift():
    types = {c: "text" for c in vehicle.SOURCES}
    sql = vehicle.insert_sql(types)
    assert "coalesce((v.seats)::text, (g.seats)::text)" in sql
    assert "WHEN 'headlight_type_code' THEN 'headlight_type'" in sql
    assert "v.listings > 0 OR v.status = 'verified'" in sql
    with pytest.raises(RuntimeError, match="differ"):
        vehicle.insert_sql({**types, "new_field": "text"})
