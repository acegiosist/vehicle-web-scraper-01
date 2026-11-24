"""Identity (makes, models, aliases), cleaned listings and the review queue (``kb clean``).

* ``kb.exclusion_reason``: why a listing stays out of the knowledge base (classic, heavy,
  machinery, ...). Excluded listings keep a ``kb.clean_listing`` row, so including them later
  needs no re-import.
* ``kb.make`` / ``kb.model`` with spelling-insensitive aliases (``compact_key``). A manual
  alias or status (``source = 'manual'``) is never overwritten by the rules.
* ``kb.clean_listing``: the current version of each staging listing after cleaning: resolved
  make/model, trim without mechanical words, catalog-checked key fields, the rest of the schema
  in ``specs`` and where each value came from in ``provenance``. Rebuilt on every run.
* ``kb.review_item``: what the rules can't settle. One row per case for good: a decided case
  is never asked again; a pending case the rules no longer see becomes ``obsolete``.

Revision ID: 0004_identity_clean
Revises: 0003_fuel_flex
"""
from __future__ import annotations

from alembic import op

revision = "0004_identity_clean"
down_revision = "0003_fuel_flex"
branch_labels = None
depends_on = None

EXCLUSION_REASONS = [
    ("Classic", "Clásico (año modelo anterior a 1990)", "Classic (model year before 1990)"),
    ("YearOutOfRange", "Año modelo fuera de rango", "Model year out of range"),
    ("Heavy", "Vehículo pesado (camión, bus)", "Heavy vehicle (truck, bus)"),
    ("Machinery", "Maquinaria", "Machinery"),
    ("GolfCart", "Carrito de golf", "Golf cart"),
    ("Bicycle", "Bicicleta", "Bicycle"),
    ("Trailer", "Remolque", "Trailer"),
    ("ATV", "Cuatrimoto / UTV", "ATV / UTV"),
]
MAKE_CLASSES = ("car", "motorcycle", "heavy", "machinery", "golf_cart", "bicycle", "trailer", "atv")
REVIEW_ISSUES = ("unknown_make", "missing_make", "weak_model", "model_is_attributes",
                 "field_conflict", "implausible_value")


def _lit(value) -> str:
    return "NULL" if value is None else "'" + str(value).replace("'", "''") + "'"


def _in(values) -> str:
    return "(" + ", ".join(_lit(v) for v in values) + ")"


def upgrade() -> None:
    op.execute("""
CREATE TABLE kb.exclusion_reason (
    code text PRIMARY KEY CHECK (code ~ '^[A-Za-z0-9]+$'),
    name_es text NOT NULL,
    name_en text NOT NULL,
    sort_order smallint NOT NULL DEFAULT 0,
    active boolean NOT NULL DEFAULT true
)""")
    op.execute("COMMENT ON TABLE kb.exclusion_reason IS 'Catálogo: por qué un anuncio queda fuera de la base'")
    rows = ",\n    ".join(f"({_lit(c)}, {_lit(es)}, {_lit(en)}, {i + 1})"
                          for i, (c, es, en) in enumerate(EXCLUSION_REASONS))
    op.execute(f"INSERT INTO kb.exclusion_reason (code, name_es, name_en, sort_order) VALUES\n    {rows}")

    op.execute(f"""
CREATE TABLE kb.make (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL UNIQUE,
    slug text NOT NULL UNIQUE,
    country_of_origin text,
    default_class text CHECK (default_class IN {_in(MAKE_CLASSES)}),
    status text NOT NULL CHECK (status IN ('accepted', 'pending_review', 'rejected')),
    source text NOT NULL CHECK (source IN ('seed', 'rule', 'manual')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
)""")
    op.execute("COMMENT ON COLUMN kb.make.default_class IS "
               "'Lo que fabrica la marca: car/motorcycle entran; heavy, machinery, ... se excluyen'")
    op.execute("""
CREATE TABLE kb.make_alias (
    alias_key text PRIMARY KEY CHECK (alias_key ~ '^[a-z0-9]+$'),
    make_id bigint NOT NULL REFERENCES kb.make(id) ON DELETE CASCADE,
    source text NOT NULL CHECK (source IN ('seed', 'rule', 'manual')),
    created_at timestamptz NOT NULL DEFAULT now()
)""")
    op.execute("""
CREATE TABLE kb.model (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    make_id bigint NOT NULL REFERENCES kb.make(id) ON DELETE CASCADE,
    name text NOT NULL,
    slug text NOT NULL,
    vehicle_class_code text REFERENCES kb.vehicle_class(code),
    status text NOT NULL CHECK (status IN ('accepted', 'pending_review', 'rejected')),
    source text NOT NULL CHECK (source IN ('seed', 'rule', 'manual')),
    listings integer NOT NULL DEFAULT 0,
    sites integer NOT NULL DEFAULT 0,
    merged_into bigint REFERENCES kb.model(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (make_id, slug),
    CHECK (merged_into IS NULL OR merged_into <> id)
)""")
    op.execute("COMMENT ON COLUMN kb.model.listings IS 'Anuncios vigentes con este modelo (último kb clean)'")
    op.execute("""
CREATE TABLE kb.model_alias (
    make_id bigint NOT NULL REFERENCES kb.make(id) ON DELETE CASCADE,
    alias_key text NOT NULL CHECK (alias_key ~ '^[a-z0-9]+$'),
    model_id bigint NOT NULL REFERENCES kb.model(id) ON DELETE CASCADE,
    source text NOT NULL CHECK (source IN ('seed', 'rule', 'manual')),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (make_id, alias_key)
)""")

    op.execute("""
CREATE TABLE kb.clean_listing (
    source_site text NOT NULL,
    listing_id text NOT NULL,
    raw_version integer NOT NULL,
    country_code text NOT NULL REFERENCES kb.country(code),
    listed_at timestamptz,
    model_year integer,
    make_id bigint REFERENCES kb.make(id),
    model_id bigint REFERENCES kb.model(id),
    trim_name text,
    trim_raw text,
    vehicle_class_code text REFERENCES kb.vehicle_class(code),
    excluded_reason text REFERENCES kb.exclusion_reason(code),
    body_style_code text REFERENCES kb.body_style(code),
    fuel_type_code text REFERENCES kb.fuel_type(code),
    transmission_type_code text REFERENCES kb.transmission_type(code),
    drivetrain_code text REFERENCES kb.drivetrain(code),
    engine_displacement_l numeric(6, 3) CHECK (engine_displacement_l > 0 AND engine_displacement_l <= 20),
    engine_cylinders smallint CHECK (engine_cylinders BETWEEN 1 AND 16),
    horsepower_hp smallint CHECK (horsepower_hp BETWEEN 1 AND 2000),
    doors smallint CHECK (doors BETWEEN 0 AND 6),
    seats smallint CHECK (seats BETWEEN 1 AND 80),
    specs jsonb NOT NULL DEFAULT '{}'::jsonb,
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    price numeric(16, 2),
    currency_code text,
    mileage_km integer,
    cleaned_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_site, listing_id),
    FOREIGN KEY (source_site, listing_id, raw_version)
        REFERENCES staging.raw_listing (source_site, listing_id, version)
)""")
    op.execute("CREATE INDEX clean_listing_model ON kb.clean_listing (model_id)")
    op.execute("CREATE INDEX clean_listing_make ON kb.clean_listing (make_id)")
    op.execute("COMMENT ON TABLE kb.clean_listing IS "
               "'Versión vigente de cada anuncio ya limpia; se reconstruye en cada kb clean'")
    op.execute("COMMENT ON COLUMN kb.clean_listing.provenance IS "
               "'Por campo: de dónde salió el valor (listing = campo del anuncio, model_text / trim_text = "
               "palabra en el nombre del modelo o la versión)'")
    op.execute("COMMENT ON COLUMN kb.clean_listing.specs IS "
               "'Demás campos del esquema (equipamiento, tanque, consumo...) con valor, ya tipados'")

    op.execute(f"""
CREATE TABLE kb.review_item (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity_type text NOT NULL CHECK (entity_type IN ('make', 'model', 'listing')),
    entity_key text NOT NULL,
    field text NOT NULL DEFAULT '',
    issue text NOT NULL CHECK (issue IN {_in(REVIEW_ISSUES)}),
    current_value jsonb,
    proposed_value jsonb,
    evidence jsonb NOT NULL DEFAULT '{{}}'::jsonb,
    listings_affected integer NOT NULL DEFAULT 0,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'corrected', 'obsolete')),
    corrected_value jsonb,
    decided_by text,
    decided_at timestamptz,
    note text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (entity_type, entity_key, field, issue),
    CHECK ((status IN ('approved', 'rejected', 'corrected')) = (decided_at IS NOT NULL))
)""")
    op.execute("CREATE INDEX review_item_pending ON kb.review_item (issue) WHERE status = 'pending'")
    op.execute("COMMENT ON COLUMN kb.review_item.entity_key IS "
               "'make/model: su id; listing: sitio:id_anuncio'")

    op.execute("""
CREATE TABLE kb.clean_run (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at timestamptz NOT NULL DEFAULT now(),
    summary jsonb NOT NULL
)""")


def downgrade() -> None:
    for table in ("clean_run", "review_item", "clean_listing", "model_alias", "model", "make_alias",
                  "make", "exclusion_reason"):
        op.execute(f"DROP TABLE kb.{table}")
