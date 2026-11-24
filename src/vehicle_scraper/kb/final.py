"""``kb.final_listing``: each in-scope listing's final record (migration 0011), written by ``kb build``.

Decided rules:

* **The knowledge base wins.** Each column lists its sources in order (``SOURCES``): a level's
  published value first (variant, then generation for seats), the listing's own value last, so
  the listing only fills what the levels don't have. Fields the levels don't hold (price,
  mileage, year, link) always come from the listing.
* **Every in-scope listing** gets a row; an unassigned one keeps what it does inherit (its
  generation, when known) plus its own values, and ``unassigned_reason``. Excluded listings
  have no row.
* **Evolution notes** apply from their year on; with several notes for a field, the latest one
  not after the listing's year wins. Before that, and without a model year, the variant's
  published value stays.

Column types are read from the table itself, so the only frozen list is the migration's.
"""
from __future__ import annotations

from ..models import FEATURE_FIELDS
from .levels import COLUMN_OF, LISTING_FIELD_OF

TABLE = "kb.final_listing"


def _own(field: str) -> str:
    """The listing's own value of a schema field kept in clean_listing.specs."""
    return f"l.specs->>'{field}'"


# column -> SQL sources, most trusted first (aliases in _FROM).
SOURCES: dict[str, list[str]] = {
    "source_site": ["l.source_site"],
    "listing_id": ["l.listing_id"],
    "raw_version": ["l.raw_version"],
    "country_code": ["l.country_code"],
    "source_url": ["s.data->>'source_url'"],
    "listed_at": ["l.listed_at"],
    "price": ["l.price"],
    "currency": ["l.currency_code"],
    "mileage_km": ["l.mileage_km"],
    "generation_id": ["ll.generation_id"],
    "powertrain_id": ["ll.powertrain_id"],
    "variant_id": ["ll.variant_id"],
    "unassigned_reason": ["ll.unassigned_reason"],
    "vehicle_class_code": ["l.vehicle_class_code"],
    "make_id": ["l.make_id"],
    "make": ["k.name"],
    "model_id": ["l.model_id"],
    "model": ["m.name"],
    "trim": ["v.trim_name", "l.trim_name"],
    "model_year": ["l.model_year"],
    "body_style": ["g.body_style_code", "l.body_style_code"],
    "country_of_manufacture": ["v.country_of_manufacture", _own("country_of_manufacture")],
    "generation_name": ["g.name"],
    "segment_code": ["g.segment_code"],
    "length_mm": ["g.length_mm"],
    "width_mm": ["g.width_mm"],
    "height_mm": ["g.height_mm"],
    "wheelbase_mm": ["g.wheelbase_mm"],
    "engine_displacement_l": ["p.engine_displacement_l", "l.engine_displacement_l"],
    "engine_cylinders": ["p.engine_cylinders", "l.engine_cylinders"],
    "horsepower_hp": ["p.horsepower_hp", "l.horsepower_hp"],
    "fuel_type": ["p.fuel_type_code", "l.fuel_type_code"],
    "fuel_tank_capacity_l": ["g.fuel_tank_capacity_l", _own("fuel_tank_capacity_l")],
    "transmission_type": ["p.transmission_type_code", "l.transmission_type_code"],
    "drivetrain": ["p.drivetrain_code", "l.drivetrain_code"],
    "seats": ["v.seats", "g.seats", "l.seats"],
    "doors": ["g.doors", "l.doors"],
    "cargo_capacity_l": ["g.cargo_capacity_l", _own("cargo_capacity_l")],
    "wheel_size_in": ["v.wheel_size_in", _own("wheel_size_in")],
    "tire_size": ["v.tire_size", _own("tire_size")],
    "fuel_economy_kml": ["p.fuel_economy_kml", _own("fuel_economy_kml")],
    "ev_range_km": ["p.ev_range_km", _own("ev_range_km")],
    "ev_charging_speed_kw": ["p.ev_charging_speed_kw", _own("ev_charging_speed_kw")],
    "engine_code": ["p.engine_code"],
    "engine_name": ["p.engine_name"],
    "torque_nm": ["p.torque_nm"],
    "gears": ["p.gears"],
    **{f: [f"v.{COLUMN_OF.get(f, f)}", _own(f)] for f in FEATURE_FIELDS},
}

_FROM = """
FROM kb.clean_listing l
JOIN kb.listing_level ll ON ll.source_site = l.source_site AND ll.listing_id = l.listing_id
LEFT JOIN staging.raw_listing s ON s.source_site = l.source_site AND s.listing_id = l.listing_id
     AND s.version = l.raw_version
LEFT JOIN kb.make k ON k.id = l.make_id
LEFT JOIN kb.model m ON m.id = l.model_id
LEFT JOIN kb.generation g ON g.id = ll.generation_id
LEFT JOIN kb.powertrain p ON p.id = ll.powertrain_id
LEFT JOIN kb.commercial_variant v ON v.id = ll.variant_id
WHERE l.excluded_reason IS NULL"""

INTEGER_TYPES = {"smallint", "integer", "bigint"}


def column_types(cur) -> dict[str, str]:
    """The table's columns in order (but built_at, which defaults), with their SQL types."""
    cur.execute("""
SELECT a.attname, format_type(a.atttypid, a.atttypmod) FROM pg_attribute a
WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped AND a.attname <> 'built_at'
ORDER BY a.attnum""", (TABLE,))
    return dict(cur.fetchall())


def _cast(expr: str, sql_type: str) -> str:
    # specs hold JSON numbers as text ("17" or "17.0"): integers go through numeric, rounded
    if sql_type in INTEGER_TYPES:
        return f"round(({expr})::numeric)::{sql_type}"
    return f"({expr})::{sql_type}"


def insert_sql(types: dict[str, str]) -> str:
    if set(types) != set(SOURCES):
        raise RuntimeError(f"{TABLE} and final.SOURCES differ: {sorted(set(types) ^ set(SOURCES))} "
                           "(a schema field needs a migration and a source here)")
    exprs = []
    for column, sql_type in types.items():
        casts = [_cast(src, sql_type) for src in SOURCES[column]]
        exprs.append(casts[0] if len(casts) == 1 else f"coalesce({', '.join(casts)})")
    return f"INSERT INTO {TABLE} ({', '.join(types)})\nSELECT {', '.join(exprs)}{_FROM}"


def write_final(cur) -> dict:
    """Rebuild the table from the current levels and listings (inside the build's transaction)."""
    types = column_types(cur)
    cur.execute(f"DELETE FROM {TABLE}")
    cur.execute(insert_sql(types))
    rows = cur.rowcount
    applied = 0
    cur.execute("SELECT variant_id, field, value, year_from FROM kb.evolution_note ORDER BY year_from, id")
    for variant_id, field, value, year_from in cur.fetchall():
        column = LISTING_FIELD_OF.get(field, field)          # headlight_type_code -> headlight_type
        if column not in types:
            continue
        # ascending years: a later note overwrites an earlier one for the years it covers
        cur.execute(f"UPDATE {TABLE} SET {column} = %s::{types[column]} "
                    "WHERE variant_id = %s AND model_year >= %s", (value, variant_id, year_from))
        applied += cur.rowcount
    return {"rows": rows, "evolution_notes_applied": applied}
