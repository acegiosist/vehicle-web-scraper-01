"""The frozen migration columns must match kb/fields.py (and so models.py)."""
import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("psycopg")
pytest.importorskip("alembic")

from vehicle_scraper.kb.fields import EQUIP_FIELDS, MECH_FIELDS, enum_values, field_kind

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0001_kb_schema.py"
PG = {"bool": "boolean", "int": "integer", "float": "double precision", "enum": "text", "text": "text"}


def _migration():
    spec = importlib.util.spec_from_file_location("m0001", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_columns_match_models():
    m = _migration()
    assert [c[0] for c in m.MECH_COLUMNS] == MECH_FIELDS, "models.py changed: add a migration"
    assert [c[0] for c in m.EQUIP_COLUMNS] == EQUIP_FIELDS, "models.py changed: add a migration"
    for name, typ, _ in m.MECH_COLUMNS + m.EQUIP_COLUMNS:
        assert typ == PG[field_kind(name)], name


def test_enums_match_models():
    m = _migration()
    assert m.FUEL == enum_values("fuel_type")
    assert m.TRANSMISSION == enum_values("transmission_type")
    assert m.DRIVETRAIN == enum_values("drivetrain")
    assert m.BODY == enum_values("body_style")
