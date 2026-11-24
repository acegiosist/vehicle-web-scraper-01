"""``kb.final_listing``: each listing's final record, what it inherits from the three levels.

One row per in-scope listing (excluded ones aren't here), rebuilt at the end of every
``kb build`` (``kb/final.py``). Columns follow the 63-field schema (``models.py``) with the same
names, plus what only the levels hold (segment, dimensions, engine code, torque, gears) and
the listing's own price, mileage and link:

* The knowledge base wins: a level's published value (manual > external > listings > ai)
  replaces the listing's; the listing's value only fills what the levels don't have.
* An unassigned listing keeps what it does inherit (its generation, when known) and its own
  values, with ``unassigned_reason`` saying why.
* No foreign keys besides the cascade from ``kb.clean_listing``: every value comes from a
  table that already has them, and ~15 checks per row made the rebuild 3x slower.
* Types are wide on purpose (numeric, integer): a listing's own value fills a gap as it is,
  and an odd one must not overflow a column and stop the whole build.
* Evolution notes apply from their year on (the latest one not after the listing's year);
  before that, and for listings without a year, the variant's published value.

Like ``kb.listing_level``, it empties when ``kb clean`` rebuilds ``kb.clean_listing`` and is
filled again by the next ``kb build``. Column lists are frozen here;
``tests/test_kb_final.py`` compares them with ``kb/final.py`` and ``models.py``.
After this migration re-run ``docs/sql/portal_role.sql`` (a new table for the portal to read).

Revision ID: 0011_final_listing
Revises: 0010_powertrain_rejected
"""
from __future__ import annotations

from alembic import op

revision = "0011_final_listing"
down_revision = "0010_powertrain_rejected"
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
CREATE TABLE kb.final_listing (
    source_site text NOT NULL,
    listing_id text NOT NULL,
    raw_version integer NOT NULL,
    country_code text NOT NULL,
    source_url text,
    listed_at timestamptz,
    price numeric,
    currency text,
    mileage_km integer,
    generation_id bigint,
    powertrain_id bigint,
    variant_id bigint,
    unassigned_reason text,
    vehicle_class_code text,
    make_id bigint,
    make text,
    model_id bigint,
    model text,
    trim text,
    model_year integer,
    body_style text,
    country_of_manufacture text,
    generation_name text,
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
    built_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_site, listing_id),
    FOREIGN KEY (source_site, listing_id) REFERENCES kb.clean_listing (source_site, listing_id) ON DELETE CASCADE
)""")
    op.execute("CREATE INDEX final_listing_variant ON kb.final_listing (variant_id)")
    op.execute("CREATE INDEX final_listing_model ON kb.final_listing (model_id, model_year)")
    op.execute("COMMENT ON TABLE kb.final_listing IS "
               "'Ficha final de cada anuncio en alcance: lo que hereda de los tres niveles (gana la base; el "
               "anuncio solo llena huecos) con las notas de evolución según su año. La llena kb build'")


def downgrade() -> None:
    op.execute("DROP TABLE kb.final_listing")
