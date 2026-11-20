"""Which schema fields live where in the knowledge base, derived from ``models.py``.

* KEY_FIELDS identify a variant (with model, trim and model year).
* MECH_FIELDS form the mechanical sheet (``kb.variant_spec``), shared across countries.
* EQUIP_FIELDS form the equipment sheet (``kb.variant_market_spec``), one per country.

``tests/test_kb_migrations.py`` checks that the migration's columns match these lists, so
a change in ``models.py`` fails a test until a new migration adds the column.
"""
from __future__ import annotations

from typing import Literal, Optional, get_args, get_origin, Union

from ..models import BOOLEAN_FIELDS, FEATURE_FIELDS, TECH_FIELDS, VehicleRecord

KEY_FIELDS = ["engine_displacement_l", "fuel_type", "transmission_type", "drivetrain"]
MECH_FIELDS = [f for f in TECH_FIELDS if f not in KEY_FIELDS] + ["body_style", "country_of_manufacture"]
EQUIP_FIELDS = list(FEATURE_FIELDS)
SPEC_FIELDS = MECH_FIELDS + EQUIP_FIELDS

# Reviewed one by one when they come from the AI without listing consensus behind them.
CRITICAL_FIELDS = {"engine_displacement_l", "horsepower_hp", "fuel_type", "transmission_type",
                   "drivetrain", "body_style", "seats", "doors"}
# Usually constant within a model generation: may be inherited from neighbouring years.
GENERATION_CONSTANT = ["doors", "seats", "fuel_tank_capacity_l", "cargo_capacity_l"]

# Sanity ranges (all vehicle classes: motorcycles, cars, buses, trucks). Class-specific
# plausibility lives in consensus.py; these only reject impossible values.
RANGES: dict[str, tuple[float, float]] = {
    "engine_displacement_l": (0.04, 20), "engine_cylinders": (1, 16), "horsepower_hp": (1, 2000),
    "fuel_tank_capacity_l": (1, 1500), "seats": (1, 80), "doors": (0, 6),
    "cargo_capacity_l": (10, 100000), "wheel_size_in": (8, 30), "fuel_economy_kml": (1, 100),
    "ev_range_km": (10, 1500), "ev_charging_speed_kw": (1, 1000), "airbags_count": (0, 14),
    "screen_size_in": (2, 25),
}


def _inner(annotation):
    if get_origin(annotation) is Union:
        args = [a for a in get_args(annotation) if a is not type(None)]
        return args[0] if len(args) == 1 else annotation
    return annotation


def field_kind(name: str) -> str:
    """'bool' | 'int' | 'float' | 'enum' | 'text' for a VehicleRecord field."""
    ann = _inner(VehicleRecord.model_fields[name].annotation)
    if get_origin(ann) is Literal:
        return "enum"
    return {bool: "bool", int: "int", float: "float"}.get(ann, "text")


def enum_values(name: str) -> list[str]:
    return list(get_args(_inner(VehicleRecord.model_fields[name].annotation)))


def coerce(name: str, value) -> Optional[object]:
    """A value of the right Python type for ``name``, or None if it doesn't fit."""
    if value is None:
        return None
    kind = field_kind(name)
    try:
        if kind == "bool":
            return bool(value) if isinstance(value, (bool, int)) else None
        if kind == "int":
            v = int(round(float(value)))
        elif kind == "float":
            v = round(float(value), 3)
        elif kind == "enum":
            return value if value in enum_values(name) else None
        else:
            return str(value)
    except (TypeError, ValueError):
        return None
    lo, hi = RANGES.get(name, (float("-inf"), float("inf")))
    return v if lo <= v <= hi else None


UNITS = {"_l": "L", "_hp": "hp", "_in": "in", "_kml": "km/L", "_km": "km", "_kw": "kW"}


def field_unit(name: str) -> Optional[str]:
    return next((u for suffix, u in UNITS.items() if name.endswith(suffix)), None)


def fields_catalog() -> dict:
    """Type, range, unit and allowed values of every reviewable field, for the review website
    (`kb fields-json`). Deterministic, so the generated file only changes when the schema does."""
    out = {}
    for name in KEY_FIELDS + SPEC_FIELDS:
        kind = field_kind(name)
        entry: dict = {"kind": kind,
                       "group": "key" if name in KEY_FIELDS else "mech" if name in MECH_FIELDS else "equip",
                       "critical": name in CRITICAL_FIELDS, "unit": field_unit(name)}
        if kind == "enum":
            entry["values"] = enum_values(name)
        if name in RANGES:
            entry["range"] = list(RANGES[name])
        out[name] = entry
    return {"version": 1, "fields": out}


assert set(BOOLEAN_FIELDS) <= set(EQUIP_FIELDS)
