"""``kb.vehicle_identity``: each vehicle's identity sheet (migration 0016), written by ``kb build``.

Decided rules (2026-11-25):

* **A vehicle is a commercial variant**: generation + powertrain + country + trim, with all its
  sale years. Its sheet puts the three levels together in one row.
* **Which variants**: not rejected, with a generation, powertrain, model and make that aren't
  rejected either, and with listings in the last build or ``verified`` by a person (a
  provisional variant whose listings moved elsewhere is left out). Variants of listings that
  don't say their trim are included, with ``trim_unknown``.
* **Only the base's values**: the same columns as ``kb.final_listing`` that come from a level
  (``VALUES``, derived from ``final.SOURCES`` without the listing's own value). A listing never
  fills a gap here.
* ``sources`` says where each published value came from (manual, external, listings, ai), the
  same precedence the build publishes with; ``evolution_notes`` lists the variant's notes with
  this table's column names; ``listings`` and each level's status say how much it's backed.

Column types are read from the table itself, so the only frozen list is the migration's.
"""
from __future__ import annotations

from . import final
from .levels import LISTING_FIELD_OF, SOURCE_RANK

TABLE = "kb.vehicle_identity"
LEVEL_ALIASES = ("g.", "p.", "v.")

# final_listing columns that come from a level, with only the levels' sources (variant first).
VALUES: dict[str, list[str]] = {
    column: [s for s in sources if s.startswith(LEVEL_ALIASES)]
    for column, sources in final.SOURCES.items() if sources[0].startswith(LEVEL_ALIASES)
}


def _column_of(expr: str) -> str:
    """SQL: an evidence field (level column) as this table's column (headlight_type_code -> headlight_type)."""
    cases = " ".join(f"WHEN '{f}' THEN '{c}'" for f, c in sorted(LISTING_FIELD_OF.items()))
    return f"CASE {expr} {cases} ELSE {expr} END"


_SOURCE_RANK = "CASE e.source_kind " + " ".join(f"WHEN '{k}' THEN {r}" for k, r in SOURCE_RANK.items()) + " END"

# The best accepted evidence per column, as the build publishes it; seats: the variant's first.
_SOURCES = f"""(SELECT coalesce(jsonb_object_agg(b.col, b.source_kind), '{{}}'::jsonb) FROM (
    SELECT DISTINCT ON (c.col) c.col, c.source_kind FROM (
        SELECT {_column_of('e.field')} AS col, e.source_kind,
               CASE e.entity_type WHEN 'variant' THEN 0 ELSE 1 END AS level_rank, {_SOURCE_RANK} AS source_rank
        FROM kb.spec_evidence e
        WHERE e.status = 'accepted' AND (
              (e.entity_type = 'variant' AND e.entity_id = v.id)
           OR (e.entity_type = 'generation' AND e.entity_id = v.generation_id)
           OR (e.entity_type = 'powertrain' AND e.entity_id = v.powertrain_id))
    ) c ORDER BY c.col, c.level_rank, c.source_rank) b)"""

_NOTES = f"""(SELECT coalesce(jsonb_agg(jsonb_build_object(
        'field', {_column_of('n.field')}, 'value', n.value, 'year_from', n.year_from, 'note', n.note,
        'source', n.source) ORDER BY {_column_of('n.field')}, n.year_from), '[]'::jsonb)
    FROM kb.evolution_note n WHERE n.variant_id = v.id)"""

# column -> SQL sources, most trusted first (aliases in _FROM).
SOURCES: dict[str, list[str]] = {
    "variant_id": ["v.id"],
    "generation_id": ["v.generation_id"],
    "powertrain_id": ["v.powertrain_id"],
    "country_code": ["v.country_code"],
    "vehicle_class_code": ["m.vehicle_class_code"],
    "make_id": ["m.make_id"],
    "make": ["k.name"],
    "model_id": ["g.model_id"],
    "model": ["m.name"],
    "generation_code": ["g.code"],
    "year_from": ["g.year_from"],
    "year_to": ["g.year_to"],
    "observed_year_from": ["g.observed_year_from"],
    "observed_year_to": ["g.observed_year_to"],
    "trim_unknown": ["v.trim_unknown"],
    "sale_year_from": ["v.sale_year_from"],
    "sale_year_to": ["v.sale_year_to"],
    "generation_status": ["g.status"],
    "powertrain_status": ["p.status"],
    "variant_status": ["v.status"],
    "listings": ["v.listings"],
    **VALUES,
    "sources": [_SOURCES],
    "evolution_notes": [_NOTES],
}

_FROM = """
FROM kb.commercial_variant v
JOIN kb.generation g ON g.id = v.generation_id
JOIN kb.powertrain p ON p.id = v.powertrain_id
JOIN kb.model m ON m.id = g.model_id
JOIN kb.make k ON k.id = m.make_id
WHERE v.status <> 'rejected' AND g.status <> 'rejected' AND p.status <> 'rejected'
  AND m.status <> 'rejected' AND k.status <> 'rejected'
  AND (v.listings > 0 OR v.status = 'verified')"""


def insert_sql(types: dict[str, str]) -> str:
    if set(types) != set(SOURCES):
        raise RuntimeError(f"{TABLE} and vehicle.SOURCES differ: {sorted(set(types) ^ set(SOURCES))} "
                           "(a new column needs a migration and a source here)")
    exprs = []
    for column, sql_type in types.items():
        casts = [final.cast(src, sql_type) for src in SOURCES[column]]
        exprs.append(casts[0] if len(casts) == 1 else f"coalesce({', '.join(casts)})")
    return f"INSERT INTO {TABLE} ({', '.join(types)})\nSELECT {', '.join(exprs)}{_FROM}"


def write_identities(cur) -> dict:
    """Rebuild the table from the current levels (inside the build's transaction, after publishing)."""
    cur.execute(f"DELETE FROM {TABLE}")
    cur.execute(insert_sql(final.column_types(cur, TABLE)))
    return {"rows": cur.rowcount}
