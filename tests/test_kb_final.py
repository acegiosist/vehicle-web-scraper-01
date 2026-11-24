"""Offline: kb.final_listing's frozen columns (migration 0011) vs kb/final.py and models.py."""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from vehicle_scraper.kb import final
from vehicle_scraper.models import BOOLEAN_FIELDS, LISTING_FIELDS, SCHEMA_FIELDS

MIGRATION = (Path(__file__).resolve().parents[1] / "src" / "vehicle_scraper" / "kb" / "migrations" / "versions"
             / "0011_final_listing.py").read_text(encoding="utf-8")


def _frozen_bools() -> list[str]:
    for node in ast.walk(ast.parse(MIGRATION)):
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == "FEATURE_BOOLS":
            return ast.literal_eval(node.value)
    raise AssertionError("FEATURE_BOOLS")


def migration_columns() -> set[str]:
    body = MIGRATION.split("CREATE TABLE kb.final_listing (", 1)[1].split("built_at", 1)[0]
    named = set(re.findall(r"^\s{4}([a-z_]+) [a-z]", body, flags=re.M))
    return named | set(_frozen_bools())


def test_migration_columns_match_sources():
    assert migration_columns() == set(final.SOURCES)


def test_every_schema_field_has_a_column():
    # models.py gaining a field fails here until a migration adds its column (and a source).
    assert set(_frozen_bools()) == set(BOOLEAN_FIELDS)
    # vehicle_type is vehicle_class_code + body_style in the knowledge base; currency keeps its name
    assert set(SCHEMA_FIELDS) - {"vehicle_type"} <= set(final.SOURCES)
    assert set(LISTING_FIELDS) <= set(final.SOURCES)


def test_the_base_wins_and_the_listing_comes_last():
    for column, sources in final.SOURCES.items():
        own = [i for i, s in enumerate(sources) if s.startswith("l.")]
        assert not own or own == [len(sources) - 1], column           # the listing only fills gaps
    assert final.SOURCES["seats"] == ["v.seats", "g.seats", "l.seats"]
    assert final.SOURCES["headlight_type"][0] == "v.headlight_type_code"


def test_insert_sql_casts_and_refuses_drift():
    types = {c: "integer" if c == "doors" else "text" for c in final.SOURCES}
    sql = final.insert_sql(types)
    assert "coalesce(round((g.doors)::numeric)::integer, round((l.doors)::numeric)::integer)" in sql
    assert "(l.specs->>'sunroof')::text" in sql
    with pytest.raises(RuntimeError, match="differ"):
        final.insert_sql({**types, "new_field": "text"})
