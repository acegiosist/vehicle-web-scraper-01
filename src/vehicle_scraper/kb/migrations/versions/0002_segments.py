"""Segment catalog values.

* Cars: European size segments A-F. The body style is a separate field, so "SUV segment B"
  (Hyundai Creta) is body_style SUV + segment B; there is no SUV-B code.
* Pickups have their own segments (compact / mid-size / full-size) instead of A-F.
* Motorcycles have their own segments.

``vehicle_class_code`` says which class a segment belongs to, and ``body_style_code`` (when
set) the only body style it applies to; the generation table (a later migration) enforces both.

Revision ID: 0002_segments
Revises: 0001_catalogs_staging
"""
from __future__ import annotations

from alembic import op

revision = "0002_segments"
down_revision = "0001_catalogs_staging"
branch_labels = None
depends_on = None

# (code, name_es, name_en, vehicle_class, body_style or None)
SEGMENTS = [
    ("A", "Segmento A (urbano)", "A segment (city car)", "car", None),
    ("B", "Segmento B (pequeño)", "B segment (small)", "car", None),
    ("C", "Segmento C (compacto)", "C segment (compact)", "car", None),
    ("D", "Segmento D (mediano)", "D segment (mid-size)", "car", None),
    ("E", "Segmento E (ejecutivo)", "E segment (executive)", "car", None),
    ("F", "Segmento F (lujo)", "F segment (luxury)", "car", None),
    ("PickupCompact", "Pickup compacta", "Compact pickup", "car", "Pickup"),
    ("PickupMidsize", "Pickup mediana", "Mid-size pickup", "car", "Pickup"),
    ("PickupFullsize", "Pickup grande", "Full-size pickup", "car", "Pickup"),
    ("Scooter", "Scooter", "Scooter", "motorcycle", None),
    ("Street", "Calle / naked", "Street / naked", "motorcycle", None),
    ("Sport", "Deportiva", "Sport", "motorcycle", None),
    ("Touring", "Touring", "Touring", "motorcycle", None),
    ("DualSport", "Doble propósito / trail", "Dual-sport / adventure", "motorcycle", None),
    ("OffRoad", "Enduro / cross", "Off-road (enduro / motocross)", "motorcycle", None),
    ("Custom", "Custom / cruiser", "Custom / cruiser", "motorcycle", None),
]


def _lit(value) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def upgrade() -> None:
    # The table is empty until now, so the NOT NULL column needs no default (and the migration
    # fails, instead of guessing, if someone added rows by hand).
    op.execute("ALTER TABLE kb.segment ADD COLUMN vehicle_class_code text NOT NULL "
               "REFERENCES kb.vehicle_class(code)")
    op.execute("ALTER TABLE kb.segment ADD COLUMN body_style_code text REFERENCES kb.body_style(code)")
    op.execute("COMMENT ON COLUMN kb.segment.vehicle_class_code IS 'Clase a la que aplica el segmento'")
    op.execute("COMMENT ON COLUMN kb.segment.body_style_code IS "
               "'Si tiene valor, el segmento solo aplica a esa carrocería (p. ej. Pickup)'")
    rows = ",\n    ".join(
        "(" + ", ".join(_lit(v) for v in (code, es, en, i + 1, cls, body)) + ")"
        for i, (code, es, en, cls, body) in enumerate(SEGMENTS))
    op.execute("INSERT INTO kb.segment (code, name_es, name_en, sort_order, vehicle_class_code, "
               f"body_style_code) VALUES\n    {rows}")


def downgrade() -> None:
    codes = ", ".join(_lit(code) for code, *_ in SEGMENTS)
    op.execute(f"DELETE FROM kb.segment WHERE code IN ({codes})")
    op.execute("ALTER TABLE kb.segment DROP COLUMN body_style_code")
    op.execute("ALTER TABLE kb.segment DROP COLUMN vehicle_class_code")
