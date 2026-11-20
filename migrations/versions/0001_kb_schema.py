"""Knowledge base schema: staging + kb.

Revision ID: 0001_kb_schema
Revises:
Create Date: 2026-11-20

Hand-written (no autogenerate). Field lists are frozen here on purpose: a later change in
models.py must come with a new migration (tests/test_kb_migrations.py checks they match).
"""
from alembic import op

revision = "0001_kb_schema"
down_revision = None
branch_labels = None
depends_on = None

# --- frozen copies of kb/fields.py at the time of this migration -------------------------
FUEL = ["Gasoline", "Diesel", "Hybrid", "EV", "CNG"]
TRANSMISSION = ["Manual", "Automatic", "CVT", "DCT"]
DRIVETRAIN = ["FWD", "RWD", "AWD", "4WD", "2WD"]
BODY = ["SUV", "Sedan", "Pickup", "Hatchback", "Coupe", "Van", "Convertible", "Wagon", "Truck",
        "Minivan", "Motorcycle"]

# (column, postgres type, CHECK expression or None)
MECH_COLUMNS = [
    ("engine_cylinders", "integer", "BETWEEN 1 AND 16"),
    ("horsepower_hp", "integer", "BETWEEN 1 AND 2000"),
    ("fuel_tank_capacity_l", "double precision", "BETWEEN 1 AND 1500"),
    ("seats", "integer", "BETWEEN 1 AND 80"),
    ("doors", "integer", "BETWEEN 0 AND 6"),
    ("cargo_capacity_l", "integer", "BETWEEN 10 AND 100000"),
    ("wheel_size_in", "integer", "BETWEEN 8 AND 30"),
    ("tire_size", "text", None),
    ("fuel_economy_kml", "double precision", "BETWEEN 1 AND 100"),
    ("ev_range_km", "integer", "BETWEEN 10 AND 1500"),
    ("ev_charging_speed_kw", "double precision", "BETWEEN 1 AND 1000"),
    ("body_style", "text", "IN (%s)" % ", ".join(f"'{v}'" for v in BODY)),
    ("country_of_manufacture", "text", None),
]
EQUIP_COLUMNS = [
    ("abs", "boolean", None), ("airbags_count", "integer", "BETWEEN 0 AND 14"),
    ("stability_control", "boolean", None), ("traction_control", "boolean", None),
    ("adaptive_cruise_control", "boolean", None), ("lane_assist", "boolean", None),
    ("automatic_emergency_braking", "boolean", None), ("blind_spot_monitoring", "boolean", None),
    ("led_lights", "boolean", None), ("fog_lights", "boolean", None), ("sunroof", "boolean", None),
    ("panoramic_roof", "boolean", None), ("roof_rails", "boolean", None), ("alloy_wheels", "boolean", None),
    ("leather_seats", "boolean", None), ("power_seats", "boolean", None), ("heated_seats", "boolean", None),
    ("cooled_seats", "boolean", None), ("memory_seats", "boolean", None), ("climate_control", "boolean", None),
    ("dual_zone_ac", "boolean", None), ("keyless_entry", "boolean", None),
    ("push_button_start", "boolean", None), ("screen_size_in", "double precision", "BETWEEN 2 AND 25"),
    ("bluetooth", "boolean", None), ("apple_carplay", "boolean", None), ("android_auto", "boolean", None),
    ("navigation", "boolean", None), ("reverse_camera", "boolean", None), ("camera_360", "boolean", None),
    ("front_camera", "boolean", None), ("parking_sensors", "boolean", None),
    ("automatic_parking", "boolean", None), ("alarm", "boolean", None), ("immobilizer", "boolean", None),
    ("tow_package", "boolean", None), ("bed_liner", "boolean", None),
]


def _in(values):
    return "IN (%s)" % ", ".join(f"'{v}'" for v in values)


def _columns(cols):
    out = []
    for name, typ, check in cols:
        out.append(f"    {name} {typ}" + (f" CHECK ({name} {check})" if check else ""))
    return ",\n".join(out)


STATUS = "status text NOT NULL DEFAULT 'unresolved' CHECK (status IN ('accepted', 'unresolved', 'pending_review', 'rejected'))"
VERIFIED = "verified_by text NOT NULL DEFAULT 'unverified' CHECK (verified_by IN ('seed', 'multi_source', 'ai', 'human', 'unverified'))"
ALIAS_SOURCE = "source text NOT NULL CHECK (source IN ('seed', 'rule', 'ai', 'manual'))"


def _listing_view_sql() -> str:
    """kb.listing_standardized: every listing in the strict schema. Mechanical fields prefer
    the validated KB sheet (falling back to the listing); equipment prefers what that very car
    reports (falling back to the version's standard equipment in that country). Each field has
    a <field>__src column: 'kb', 'listing' or NULL."""
    def raw(name, typ):
        return f"(r.row->>'{name}')::{typ}"
    parts = []
    for name, typ, _ in MECH_COLUMNS:
        parts.append(f"COALESCE(vs.{name}, {raw(name, typ)}) AS {name}")
        parts.append(f"CASE WHEN vs.{name} IS NOT NULL THEN 'kb' WHEN {raw(name, typ)} IS NOT NULL "
                     f"THEN 'listing' END AS {name}__src")
    for name, typ, _ in EQUIP_COLUMNS:
        parts.append(f"COALESCE({raw(name, typ)}, ms.{name}) AS {name}")
        parts.append(f"CASE WHEN {raw(name, typ)} IS NOT NULL THEN 'listing' WHEN ms.{name} IS NOT NULL "
                     f"THEN 'kb' END AS {name}__src")
    fields = ",\n    ".join(parts)
    return f"""
CREATE VIEW kb.listing_standardized AS
SELECT
    l.source_site, l.listing_id, r.row->>'source_url' AS source_url, l.country,
    (r.row->>'price')::double precision AS price, r.row->>'currency' AS currency,
    (r.row->>'mileage_km')::integer AS mileage_km, l.listed_at,
    mk.name AS make, md.name AS model, tr.name AS trim, l.raw_year AS model_year,
    md.vehicle_class,
    CASE WHEN md.vehicle_class = 'motorcycle' THEN 'Motorcycle'
         ELSE COALESCE(vs.body_style, r.row->>'body_style') END AS vehicle_type,
    COALESCE(v.engine_displacement_l::double precision,
             (r.row->>'engine_displacement_l')::double precision) AS engine_displacement_l,
    COALESCE(v.fuel_type, r.row->>'fuel_type') AS fuel_type,
    COALESCE(v.transmission_type, r.row->>'transmission_type') AS transmission_type,
    COALESCE(v.drivetrain, r.row->>'drivetrain') AS drivetrain,
    {fields},
    l.variant_id, v.status AS variant_status, md.status AS model_status,
    mk.verified_by AS make_verified_by, md.verified_by AS model_verified_by,
    tr.verified_by AS trim_verified_by, l.match_method, l.cluster_id
FROM kb.listing l
JOIN staging.raw_listing r
  ON r.source_site = l.source_site AND r.listing_id = l.listing_id AND r.version = l.current_version
LEFT JOIN kb.make mk ON mk.id = l.make_id
LEFT JOIN kb.model md ON md.id = l.model_id
LEFT JOIN kb.trim tr ON tr.id = l.trim_id
LEFT JOIN kb.variant v ON v.id = l.variant_id
LEFT JOIN kb.variant_spec vs ON vs.variant_id = l.variant_id
LEFT JOIN kb.variant_market_spec ms ON ms.variant_id = l.variant_id AND ms.country = l.country
"""


def upgrade() -> None:
    op.execute("CREATE SCHEMA staging")
    op.execute("CREATE SCHEMA kb")

    op.execute("""
CREATE TABLE staging.import_snapshot (
    id bigserial PRIMARY KEY,
    source_file text NOT NULL,
    sha256 text NOT NULL UNIQUE,
    row_count integer NOT NULL,
    new_versions integer NOT NULL DEFAULT 0,
    imported_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE staging.raw_listing (
    source_site text NOT NULL,
    listing_id text NOT NULL,
    version integer NOT NULL,
    row_hash text NOT NULL,
    row jsonb NOT NULL,
    snapshot_id bigint NOT NULL REFERENCES staging.import_snapshot(id),
    valid_from timestamptz NOT NULL DEFAULT now(),
    valid_to timestamptz,
    PRIMARY KEY (source_site, listing_id, version)
);
CREATE UNIQUE INDEX raw_listing_current ON staging.raw_listing (source_site, listing_id) WHERE valid_to IS NULL;
""")

    op.execute(f"""
CREATE TABLE kb.source_site (
    site text PRIMARY KEY,
    country text NOT NULL,
    ai_allowed boolean NOT NULL,
    training_allowed boolean NOT NULL,
    notes text
);
INSERT INTO kb.source_site (site, country, ai_allowed, training_allowed, notes) VALUES
    ('carroya', 'CO', true, true, NULL),
    ('cars24', 'IN', true, true, NULL),
    ('cofino', 'GT', false, false, 'robots.txt Content-Signal: search=yes, ai-train=no, use=reference'),
    ('tucarro', 'CO', true, true, 'Mercado Libre official API'),
    ('chileautos', 'CL', true, true, NULL),
    ('truecar', 'US', true, true, NULL);

CREATE TABLE kb.make (
    id bigserial PRIMARY KEY,
    name text NOT NULL,
    slug text NOT NULL UNIQUE,
    country_of_origin text,
    {STATUS},
    {VERIFIED},
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE kb.make_alias (
    alias_key text PRIMARY KEY,
    make_id bigint NOT NULL REFERENCES kb.make(id) ON DELETE CASCADE,
    {ALIAS_SOURCE}
);
CREATE TABLE kb.model (
    id bigserial PRIMARY KEY,
    make_id bigint NOT NULL REFERENCES kb.make(id) ON DELETE CASCADE,
    name text NOT NULL,
    slug text NOT NULL,
    vehicle_class text CHECK (vehicle_class IN ('car', 'motorcycle', 'heavy')),
    year_from integer,
    year_to integer,
    {STATUS},
    {VERIFIED},
    merged_into bigint REFERENCES kb.model(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (make_id, slug)
);
CREATE TABLE kb.model_alias (
    make_id bigint NOT NULL REFERENCES kb.make(id) ON DELETE CASCADE,
    alias_key text NOT NULL,
    model_id bigint NOT NULL REFERENCES kb.model(id) ON DELETE CASCADE,
    {ALIAS_SOURCE},
    PRIMARY KEY (make_id, alias_key)
);
CREATE TABLE kb.trim (
    id bigserial PRIMARY KEY,
    model_id bigint NOT NULL REFERENCES kb.model(id) ON DELETE CASCADE,
    name text NOT NULL,
    slug text NOT NULL,
    {STATUS},
    {VERIFIED},
    merged_into bigint REFERENCES kb.trim(id),
    UNIQUE (model_id, slug)
);
CREATE TABLE kb.trim_alias (
    model_id bigint NOT NULL REFERENCES kb.model(id) ON DELETE CASCADE,
    alias_key text NOT NULL,
    trim_id bigint NOT NULL REFERENCES kb.trim(id) ON DELETE CASCADE,
    {ALIAS_SOURCE},
    PRIMARY KEY (model_id, alias_key)
);
CREATE TABLE kb.variant (
    id bigserial PRIMARY KEY,
    model_id bigint NOT NULL REFERENCES kb.model(id) ON DELETE CASCADE,
    trim_id bigint REFERENCES kb.trim(id) ON DELETE CASCADE,
    model_year integer NOT NULL CHECK (model_year BETWEEN 1900 AND 2100),
    engine_displacement_l numeric(6, 3) CHECK (engine_displacement_l BETWEEN 0.04 AND 20),
    fuel_type text CHECK (fuel_type {_in(FUEL)}),
    transmission_type text CHECK (transmission_type {_in(TRANSMISSION)}),
    drivetrain text CHECK (drivetrain {_in(DRIVETRAIN)}),
    status text NOT NULL DEFAULT 'accepted' CHECK (status IN ('accepted', 'pending_review', 'rejected')),
    {VERIFIED},
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (model_id, trim_id, model_year, engine_displacement_l,
                               fuel_type, transmission_type, drivetrain)
);
CREATE TABLE kb.variant_market (
    variant_id bigint NOT NULL REFERENCES kb.variant(id) ON DELETE CASCADE,
    country text NOT NULL,
    listings_seen integer NOT NULL DEFAULT 0,
    PRIMARY KEY (variant_id, country)
);
CREATE TABLE kb.variant_spec (
    variant_id bigint PRIMARY KEY REFERENCES kb.variant(id) ON DELETE CASCADE,
{_columns(MECH_COLUMNS)},
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE kb.variant_market_spec (
    variant_id bigint NOT NULL REFERENCES kb.variant(id) ON DELETE CASCADE,
    country text NOT NULL,
{_columns(EQUIP_COLUMNS)},
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (variant_id, country)
);
""")

    op.execute("""
CREATE TABLE kb.listing_cluster (
    id bigserial PRIMARY KEY,
    member_hash text NOT NULL UNIQUE,
    method text NOT NULL CHECK (method IN ('heuristic', 'manual')),
    members integer NOT NULL,
    undone boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE kb.listing (
    source_site text NOT NULL REFERENCES kb.source_site(site),
    listing_id text NOT NULL,
    current_version integer NOT NULL,
    first_seen timestamptz NOT NULL DEFAULT now(),
    last_seen timestamptz NOT NULL DEFAULT now(),
    country text NOT NULL,
    listed_at timestamptz,
    raw_make text,
    raw_model text,
    raw_trim text,
    raw_year integer,
    make_id bigint REFERENCES kb.make(id),
    model_id bigint REFERENCES kb.model(id),
    trim_id bigint REFERENCES kb.trim(id),
    variant_id bigint REFERENCES kb.variant(id) ON DELETE SET NULL,
    match_method text CHECK (match_method IN ('rule', 'rule_partial', 'ai', 'manual')),
    match_confidence real,
    excluded_reason text,
    cluster_id bigint REFERENCES kb.listing_cluster(id) ON DELETE SET NULL,
    PRIMARY KEY (source_site, listing_id)
);
CREATE INDEX listing_variant ON kb.listing (variant_id);
CREATE INDEX listing_model ON kb.listing (model_id);

CREATE TABLE kb.ai_run (
    id bigserial PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('identity', 'specs')),
    batch_id text UNIQUE,
    model text NOT NULL,
    effort text NOT NULL,
    status text NOT NULL DEFAULT 'prepared' CHECK (status IN ('prepared', 'submitted', 'ended', 'applied', 'canceled')),
    request_count integer NOT NULL DEFAULT 0,
    submitted_at timestamptz,
    ended_at timestamptz,
    input_tokens bigint NOT NULL DEFAULT 0,
    output_tokens bigint NOT NULL DEFAULT 0,
    cache_read_tokens bigint NOT NULL DEFAULT 0,
    est_cost_usd numeric(10, 4),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE kb.ai_decision (
    id bigserial PRIMARY KEY,
    ai_run_id bigint NOT NULL REFERENCES kb.ai_run(id) ON DELETE CASCADE,
    custom_id text NOT NULL,
    input_hash text NOT NULL UNIQUE,
    request jsonb NOT NULL,
    response jsonb,
    result_type text,
    stop_reason text,
    applied boolean NOT NULL DEFAULT false,
    UNIQUE (ai_run_id, custom_id)
);

CREATE TABLE kb.review_batch (
    id bigserial PRIMARY KEY,
    ai_run_id bigint REFERENCES kb.ai_run(id) ON DELETE CASCADE,
    scope text NOT NULL CHECK (scope IN ('identity', 'specs')),
    seed integer NOT NULL,
    sample_size integer NOT NULL,
    threshold real NOT NULL,
    min_confidence real NOT NULL,
    correct integer,
    accuracy real,
    decision text CHECK (decision IN ('accepted', 'rejected')),
    decided_by text,
    decided_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE kb.spec_evidence (
    id bigserial PRIMARY KEY,
    variant_id bigint NOT NULL REFERENCES kb.variant(id) ON DELETE CASCADE,
    country text NOT NULL DEFAULT '',
    field text NOT NULL,
    value jsonb NOT NULL,
    source_kind text NOT NULL CHECK (source_kind IN ('listing_consensus', 'listing_single', 'sibling_inference', 'ai_knowledge', 'manual')),
    support_count integer NOT NULL DEFAULT 0,
    agreement real,
    confidence real,
    status text NOT NULL CHECK (status IN ('accepted', 'accepted_sampled', 'pending_review', 'rejected')),
    sites text[] NOT NULL DEFAULT '{}',
    reason text,
    review_batch_id bigint REFERENCES kb.review_batch(id) ON DELETE SET NULL,
    ai_decision_id bigint REFERENCES kb.ai_decision(id) ON DELETE CASCADE,
    origin_key text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (variant_id, country, field, source_kind, origin_key)
);
COMMENT ON COLUMN kb.spec_evidence.country IS 'empty for mechanical fields, ISO country for equipment';

CREATE TABLE kb.spec_history (
    id bigserial PRIMARY KEY,
    variant_id bigint NOT NULL REFERENCES kb.variant(id) ON DELETE CASCADE,
    country text NOT NULL DEFAULT '',
    field text NOT NULL,
    old_value jsonb,
    new_value jsonb,
    old_source text,
    new_source text,
    reason text,
    changed_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE kb.review_item (
    id bigserial PRIMARY KEY,
    level integer NOT NULL,
    entity_type text NOT NULL CHECK (entity_type IN ('make', 'model', 'trim', 'listing', 'variant', 'spec')),
    entity_id bigint NOT NULL,
    country text NOT NULL DEFAULT '',
    field text NOT NULL DEFAULT '',
    issue text NOT NULL,
    proposed jsonb,
    current jsonb,
    evidence jsonb,
    source text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('individual', 'sample')),
    review_batch_id bigint REFERENCES kb.review_batch(id) ON DELETE SET NULL,
    evidence_id bigint REFERENCES kb.spec_evidence(id) ON DELETE CASCADE,
    ai_decision_id bigint REFERENCES kb.ai_decision(id) ON DELETE CASCADE,
    listings_affected integer NOT NULL DEFAULT 0,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'corrected')),
    corrected_value jsonb,
    reviewer text,
    decided_at timestamptz,
    note text,
    created_at timestamptz NOT NULL DEFAULT now()
);
-- one open case per thing: re-running a step never queues the same question twice
CREATE UNIQUE INDEX review_item_open ON kb.review_item (entity_type, entity_id, country, field, issue)
    WHERE status = 'pending';
""")

    op.execute(_listing_view_sql())
    op.execute("""
CREATE VIEW kb.training_safe_evidence AS
SELECT e.*
FROM kb.spec_evidence e
WHERE NOT EXISTS (
    SELECT 1 FROM unnest(e.sites) s
    JOIN kb.source_site ss ON ss.site = s
    WHERE NOT ss.training_allowed
);
""")


def downgrade() -> None:
    op.execute("DROP SCHEMA kb CASCADE")
    op.execute("DROP SCHEMA staging CASCADE")
