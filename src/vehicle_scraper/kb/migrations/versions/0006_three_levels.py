"""The three levels of the knowledge base, field evidence and evolution notes (``kb build``).

* ``kb.generation`` (level 1): model + body style + life cycle. Starts ``provisional`` (one per
  model and body, observed years); a person verifies or splits it. ``year_from``/``year_to`` are
  the official cycle (empty = not known / still on sale); ``observed_year_*`` come from listings.
  A trigger checks the segment fits the model's class and the body (pickups use pickup segments).
* ``kb.powertrain`` (level 2): per generation, identified by ``match_key`` (fuel, transmission,
  drivetrain, displacement or cylinders) frozen at creation; empty fields can be filled later.
* ``kb.commercial_variant`` (level 3): generation + powertrain + country + trim. ``trim_key = ''``
  is the "trim unknown" variant of listings that don't say their version.
* ``kb.listing_level``: where each cleaned listing landed (or why it didn't).
* ``kb.spec_evidence``: every candidate value per entity and field with its source
  (manual > external > listings > ai). The level tables hold the published (winning) value.
* ``kb.evolution_note``: a variant's field that changes from a model year on (approved by a person).

Column lists are frozen here; ``tests/test_kb_levels.py`` compares them with ``kb/levels.py``.

Revision ID: 0006_three_levels
Revises: 0005_three_wheeler
"""
from __future__ import annotations

from alembic import op

revision = "0006_three_levels"
down_revision = "0005_three_wheeler"
branch_labels = None
depends_on = None

FEATURE_BOOLS = [
    "abs", "stability_control", "traction_control", "adaptive_cruise_control", "lane_assist",
    "automatic_emergency_braking", "blind_spot_monitoring", "led_lights", "fog_lights", "sunroof",
    "panoramic_roof", "roof_rails", "alloy_wheels", "leather_seats", "power_seats", "heated_seats",
    "cooled_seats", "memory_seats", "climate_control", "dual_zone_ac", "keyless_entry", "push_button_start",
    "bluetooth", "apple_carplay", "android_auto", "navigation", "reverse_camera", "camera_360", "front_camera",
    "parking_sensors", "automatic_parking", "alarm", "immobilizer", "tow_package", "bed_liner",
]
REVIEW_ENTITIES = ("make", "model", "listing", "generation", "powertrain", "variant")
REVIEW_ISSUES = ("unknown_make", "missing_make", "weak_model", "model_is_attributes", "field_conflict",
                 "implausible_value", "generation_split", "spec_disagreement", "evolution_note")
UNASSIGNED = ("model_not_accepted", "ambiguous_body", "no_generation_for_year", "ambiguous_powertrain")
SOURCES = ("manual", "external", "listings", "ai")


def _in(values) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.execute("""
CREATE TABLE kb.generation (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    model_id bigint NOT NULL REFERENCES kb.model(id),
    body_style_code text REFERENCES kb.body_style(code),
    name text NOT NULL,
    code text,
    status text NOT NULL DEFAULT 'provisional' CHECK (status IN ('provisional', 'verified', 'rejected')),
    source text NOT NULL DEFAULT 'rule' CHECK (source IN ('rule', 'manual', 'external', 'ai')),
    year_from integer CHECK (year_from BETWEEN 1900 AND 2100),
    year_to integer CHECK (year_to BETWEEN 1900 AND 2100),
    observed_year_from integer,
    observed_year_to integer,
    segment_code text REFERENCES kb.segment(code),
    length_mm integer CHECK (length_mm BETWEEN 1000 AND 20000),
    width_mm integer CHECK (width_mm BETWEEN 500 AND 3000),
    height_mm integer CHECK (height_mm BETWEEN 500 AND 4500),
    wheelbase_mm integer CHECK (wheelbase_mm BETWEEN 500 AND 8000),
    doors smallint CHECK (doors BETWEEN 0 AND 6),
    seats smallint CHECK (seats BETWEEN 1 AND 80),
    cargo_capacity_l integer CHECK (cargo_capacity_l BETWEEN 1 AND 100000),
    fuel_tank_capacity_l numeric(6, 1) CHECK (fuel_tank_capacity_l BETWEEN 1 AND 1500),
    listings integer NOT NULL DEFAULT 0,
    split_from bigint REFERENCES kb.generation(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (year_to IS NULL OR year_from IS NULL OR year_to >= year_from)
)""")
    op.execute("CREATE INDEX generation_model ON kb.generation (model_id, body_style_code)")
    op.execute("COMMENT ON TABLE kb.generation IS 'Nivel 1: generación / plataforma (modelo + carrocería + ciclo)'")
    op.execute("COMMENT ON COLUMN kb.generation.year_to IS 'Último año del ciclo; vacío = vigente o no confirmado'")
    op.execute("""
CREATE FUNCTION kb.check_generation_segment() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE seg record; cls text;
BEGIN
    IF NEW.segment_code IS NULL THEN RETURN NEW; END IF;
    SELECT * INTO seg FROM kb.segment WHERE code = NEW.segment_code;
    SELECT vehicle_class_code INTO cls FROM kb.model WHERE id = NEW.model_id;
    IF cls IS NOT NULL AND seg.vehicle_class_code <> cls THEN
        RAISE EXCEPTION 'segment % is for %, not for a % model', NEW.segment_code, seg.vehicle_class_code, cls;
    END IF;
    IF seg.body_style_code IS NOT NULL AND seg.body_style_code IS DISTINCT FROM NEW.body_style_code THEN
        RAISE EXCEPTION 'segment % only applies to body style %', NEW.segment_code, seg.body_style_code;
    END IF;
    IF NEW.body_style_code = 'Pickup' AND seg.body_style_code IS DISTINCT FROM 'Pickup' THEN
        RAISE EXCEPTION 'a pickup generation needs a pickup segment, not %', NEW.segment_code;
    END IF;
    RETURN NEW;
END $$""")
    op.execute("CREATE TRIGGER generation_segment BEFORE INSERT OR UPDATE OF segment_code, body_style_code, model_id "
               "ON kb.generation FOR EACH ROW EXECUTE FUNCTION kb.check_generation_segment()")

    op.execute("""
CREATE TABLE kb.powertrain (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    generation_id bigint NOT NULL REFERENCES kb.generation(id),
    match_key text NOT NULL,
    status text NOT NULL DEFAULT 'provisional' CHECK (status IN ('provisional', 'verified', 'rejected')),
    source text NOT NULL DEFAULT 'rule' CHECK (source IN ('rule', 'manual', 'external', 'ai')),
    engine_code text,
    engine_name text,
    engine_displacement_l numeric(6, 3) CHECK (engine_displacement_l > 0 AND engine_displacement_l <= 20),
    engine_cylinders smallint CHECK (engine_cylinders BETWEEN 1 AND 16),
    fuel_type_code text REFERENCES kb.fuel_type(code),
    horsepower_hp integer CHECK (horsepower_hp BETWEEN 1 AND 2000),
    torque_nm integer CHECK (torque_nm BETWEEN 1 AND 5000),
    transmission_type_code text REFERENCES kb.transmission_type(code),
    gears smallint CHECK (gears BETWEEN 1 AND 12),
    drivetrain_code text REFERENCES kb.drivetrain(code),
    fuel_economy_kml numeric(5, 2) CHECK (fuel_economy_kml BETWEEN 1 AND 100),
    ev_range_km integer CHECK (ev_range_km BETWEEN 1 AND 2000),
    ev_charging_speed_kw numeric(6, 1) CHECK (ev_charging_speed_kw BETWEEN 1 AND 1000),
    listings integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (generation_id, match_key),
    UNIQUE (id, generation_id)
)""")
    op.execute("COMMENT ON TABLE kb.powertrain IS 'Nivel 2: tren motriz de una generación'")
    op.execute("COMMENT ON COLUMN kb.powertrain.match_key IS "
               "'combustible|transmisión|tracción|cilindraje|cilindros con que se creó (vacío = no se sabía)'")

    bools = ",\n    ".join(f"{f} boolean" for f in FEATURE_BOOLS)
    op.execute(f"""
CREATE TABLE kb.commercial_variant (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    generation_id bigint NOT NULL REFERENCES kb.generation(id),
    powertrain_id bigint NOT NULL,
    country_code text NOT NULL REFERENCES kb.country(code),
    trim_name text,
    trim_key text NOT NULL DEFAULT '',
    trim_unknown boolean GENERATED ALWAYS AS (trim_key = '') STORED,
    status text NOT NULL DEFAULT 'provisional' CHECK (status IN ('provisional', 'verified', 'rejected')),
    sale_year_from integer,
    sale_year_to integer,
    listings integer NOT NULL DEFAULT 0,
    country_of_manufacture text,
    seats smallint CHECK (seats BETWEEN 1 AND 80),
    airbags_count smallint CHECK (airbags_count BETWEEN 0 AND 14),
    screen_size_in numeric(4, 1) CHECK (screen_size_in BETWEEN 2 AND 25),
    wheel_size_in smallint CHECK (wheel_size_in BETWEEN 8 AND 30),
    tire_size text,
    headlight_type_code text REFERENCES kb.headlight_type(code),
    brake_front_code text REFERENCES kb.brake_type(code),
    brake_rear_code text REFERENCES kb.brake_type(code),
    wireless_charger boolean,
    {bools},
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (powertrain_id, generation_id) REFERENCES kb.powertrain (id, generation_id),
    UNIQUE (generation_id, powertrain_id, country_code, trim_key),
    CHECK ((trim_key = '') = (trim_name IS NULL))
)""")
    op.execute("COMMENT ON TABLE kb.commercial_variant IS "
               "'Nivel 3: variante comercial (generación + tren motriz + país + versión)'")
    op.execute("COMMENT ON COLUMN kb.commercial_variant.trim_unknown IS "
               "'Anuncios que no dicen su versión: su equipamiento no se mezcla con el de las versiones conocidas'")
    op.execute("COMMENT ON COLUMN kb.commercial_variant.seats IS "
               "'Solo si esta versión difiere de la generación (p. ej. 7 asientos); vacío = la de la generación'")

    op.execute(f"""
CREATE TABLE kb.listing_level (
    source_site text NOT NULL,
    listing_id text NOT NULL,
    generation_id bigint REFERENCES kb.generation(id),
    powertrain_id bigint REFERENCES kb.powertrain(id),
    variant_id bigint REFERENCES kb.commercial_variant(id),
    unassigned_reason text CHECK (unassigned_reason IN {_in(UNASSIGNED)}),
    PRIMARY KEY (source_site, listing_id),
    FOREIGN KEY (source_site, listing_id) REFERENCES kb.clean_listing (source_site, listing_id) ON DELETE CASCADE,
    CHECK ((variant_id IS NULL) = (unassigned_reason IS NOT NULL))
)""")
    op.execute("CREATE INDEX listing_level_variant ON kb.listing_level (variant_id)")

    op.execute(f"""
CREATE TABLE kb.spec_evidence (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity_type text NOT NULL CHECK (entity_type IN ('generation', 'powertrain', 'variant')),
    entity_id bigint NOT NULL,
    field text NOT NULL,
    source_kind text NOT NULL CHECK (source_kind IN {_in(SOURCES)}),
    value jsonb NOT NULL,
    status text NOT NULL CHECK (status IN ('accepted', 'pending', 'rejected')),
    support integer NOT NULL DEFAULT 0,
    agreement real,
    detail jsonb NOT NULL DEFAULT '{{}}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (entity_type, entity_id, field, source_kind)
)""")
    op.execute("COMMENT ON TABLE kb.spec_evidence IS "
               "'Valores candidatos por campo y fuente; gana manual > external > listings > ai (solo accepted)'")

    op.execute("""
CREATE TABLE kb.evolution_note (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    variant_id bigint NOT NULL REFERENCES kb.commercial_variant(id),
    field text NOT NULL,
    value jsonb NOT NULL,
    year_from integer NOT NULL CHECK (year_from BETWEEN 1900 AND 2100),
    note text,
    source text NOT NULL CHECK (source IN ('manual', 'external', 'ai')),
    review_item_id bigint REFERENCES kb.review_item(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (variant_id, field, year_from)
)""")
    op.execute("COMMENT ON TABLE kb.evolution_note IS "
               "'Nota de evolución: desde year_from el campo vale value en esa variante (no duplica la ficha)'")

    op.execute("ALTER TABLE kb.review_item DROP CONSTRAINT review_item_entity_type_check")
    op.execute(f"ALTER TABLE kb.review_item ADD CONSTRAINT review_item_entity_type_check "
               f"CHECK (entity_type IN {_in(REVIEW_ENTITIES)})")
    op.execute("ALTER TABLE kb.review_item DROP CONSTRAINT review_item_issue_check")
    op.execute(f"ALTER TABLE kb.review_item ADD CONSTRAINT review_item_issue_check CHECK (issue IN {_in(REVIEW_ISSUES)})")

    op.execute("""
CREATE TABLE kb.build_run (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at timestamptz NOT NULL DEFAULT now(),
    summary jsonb NOT NULL
)""")


def downgrade() -> None:
    op.execute("DELETE FROM kb.review_item WHERE entity_type IN ('generation', 'powertrain', 'variant') "
               "OR issue IN ('generation_split', 'spec_disagreement', 'evolution_note')")
    op.execute("ALTER TABLE kb.review_item DROP CONSTRAINT review_item_issue_check")
    op.execute("ALTER TABLE kb.review_item ADD CONSTRAINT review_item_issue_check CHECK (issue IN "
               "('unknown_make', 'missing_make', 'weak_model', 'model_is_attributes', 'field_conflict', "
               "'implausible_value'))")
    op.execute("ALTER TABLE kb.review_item DROP CONSTRAINT review_item_entity_type_check")
    op.execute("ALTER TABLE kb.review_item ADD CONSTRAINT review_item_entity_type_check CHECK (entity_type IN "
               "('make', 'model', 'listing'))")
    for table in ("build_run", "evolution_note", "spec_evidence", "listing_level", "commercial_variant",
                  "powertrain"):
        op.execute(f"DROP TABLE kb.{table}")
    op.execute("DROP TRIGGER generation_segment ON kb.generation")
    op.execute("DROP FUNCTION kb.check_generation_segment()")
    op.execute("DROP TABLE kb.generation")
