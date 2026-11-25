"""``kb.vehicle_identity``: the vehicle's identity sheet, one row per commercial variant.

Decided 2026-11-25: the portal's Fichas section shows vehicles, not listings. A vehicle is a
commercial variant (generation + powertrain + country + trim, all its sale years), and its
sheet puts the three levels together in one row, rebuilt at the end of every ``kb build``
(``kb/vehicle.py``):

* Which variants: not rejected, with a generation, powertrain, model and make that aren't
  rejected either, and with listings in the last build or verified by a person. Variants of
  listings that don't say their trim (``trim_unknown``) are included and marked.
* Values come only from the levels: the same column names as ``kb.final_listing`` (the
  schema's), a level's published value, never a listing's. Seats: the variant's, else the
  generation's.
* ``sources``: column -> source of the published value (manual, external, listings, ai), for
  the columns that come from evidence. The powertrain's key (displacement, fuel,
  transmission, drivetrain) and the identity have none.
* ``evolution_notes``: the variant's notes, ``[{field, value, year_from, note, source}]`` with
  this table's column names, by field and year.
* ``listings``: listings in the variant at the last build; plus each level's status.

Types are wide like ``kb.final_listing``. The only foreign key is the cascade from
``kb.commercial_variant``. Column lists are frozen here; ``tests/test_kb_vehicle.py`` compares
them with ``kb/vehicle.py``. After this migration re-run ``docs/sql/portal_role.sql``.

Revision ID: 0016_vehicle_identity
Revises: 0015_capture_actions
"""
from __future__ import annotations

from alembic import op

revision = "0016_vehicle_identity"
down_revision = "0015_capture_actions"
branch_labels = None
depends_on = None

# Frozen (models.BOOLEAN_FIELDS when this was written): one boolean column each.
FEATURE_BOOLS = [
    "abs", "stability_control", "traction_control", "adaptive_cruise_control", "lane_assist",
    "automatic_emergency_braking", "blind_spot_monitoring", "led_lights", "fog_lights", "sunroof",
    "panoramic_roof", "roof_rails", "alloy_wheels", "leather_seats", "power_seats", "heated_seats",
    "cooled_seats", "memory_seats", "climate_control", "dual_zone_ac", "keyless_entry", "push_button_start",
    "bluetooth", "apple_carplay", "android_auto", "navigation", "wireless_charger", "reverse_camera",
    "camera_360", "front_camera", "parking_sensors", "automatic_parking", "alarm", "immobilizer",
    "tow_package", "bed_liner",
]


def upgrade() -> None:
    bools = ",\n    ".join(f"{f} boolean" for f in FEATURE_BOOLS)
    op.execute(f"""
CREATE TABLE kb.vehicle_identity (
    variant_id bigint PRIMARY KEY REFERENCES kb.commercial_variant(id) ON DELETE CASCADE,
    generation_id bigint NOT NULL,
    powertrain_id bigint NOT NULL,
    country_code text NOT NULL,
    vehicle_class_code text,
    make_id bigint NOT NULL,
    make text NOT NULL,
    model_id bigint NOT NULL,
    model text NOT NULL,
    generation_name text NOT NULL,
    generation_code text,
    body_style text,
    year_from integer,
    year_to integer,
    observed_year_from integer,
    observed_year_to integer,
    trim text,
    trim_unknown boolean NOT NULL,
    sale_year_from integer,
    sale_year_to integer,
    generation_status text NOT NULL,
    powertrain_status text NOT NULL,
    variant_status text NOT NULL,
    listings integer NOT NULL,
    country_of_manufacture text,
    segment_code text,
    length_mm integer,
    width_mm integer,
    height_mm integer,
    wheelbase_mm integer,
    engine_displacement_l numeric,
    engine_cylinders integer,
    horsepower_hp integer,
    fuel_type text,
    fuel_tank_capacity_l numeric,
    transmission_type text,
    drivetrain text,
    seats integer,
    doors integer,
    cargo_capacity_l integer,
    wheel_size_in integer,
    tire_size text,
    fuel_economy_kml numeric,
    ev_range_km integer,
    ev_charging_speed_kw numeric,
    engine_code text,
    engine_name text,
    torque_nm integer,
    gears integer,
    airbags_count integer,
    screen_size_in numeric,
    headlight_type text,
    brake_front text,
    brake_rear text,
    {bools},
    sources jsonb NOT NULL,
    evolution_notes jsonb NOT NULL,
    built_at timestamptz NOT NULL DEFAULT now()
)""")
    op.execute("CREATE INDEX vehicle_identity_model ON kb.vehicle_identity (model_id)")
    op.execute("CREATE INDEX vehicle_identity_country ON kb.vehicle_identity (country_code)")
    op.execute("COMMENT ON TABLE kb.vehicle_identity IS "
               "'Ficha de identidad de cada variante comercial: generación, tren motriz y equipamiento en una fila, "
               "con la fuente de cada valor y sus notas de evolución. Solo valores de la base. La llena kb build'")
    op.execute("COMMENT ON COLUMN kb.vehicle_identity.sources IS "
               "'Columna -> fuente del valor publicado (manual, external, listings, ai)'")


def downgrade() -> None:
    op.execute("DROP TABLE kb.vehicle_identity")
