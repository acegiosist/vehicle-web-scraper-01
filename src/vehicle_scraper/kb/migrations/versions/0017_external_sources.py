"""External sources: their registry, evidence per source, and the portal's lookup actions.

Decided 2026-11-25:

* ``kb.external_source``: one row per automatic source (code, name, link, credit to cite, what
  it gives, ``paid``, ``active``, ``countries`` it applies to — empty = every country, seeded
  with the US only — and ``priority``, lower first). An editor changes it from the portal
  (action ``source_update``); the code that queries each source lives in ``kb/sources/``.
  Seeded: ``vpic_canada`` (NHTSA vPIC's Canadian specifications: dimensions) and
  ``fueleconomy`` (fueleconomy.gov, EPA/DOE: economy, cylinders, gears, EV range).
* ``kb.spec_evidence.source_code``: which source gave an ``external`` value, so several sources
  keep their own evidence for one field. What the capture template saved becomes ``captura``,
  which always wins among external values; then the sources' priority. Every other kind keeps
  ``''``. Precedence across kinds doesn't change: manual > external > listings > ai.
* Portal actions: ``source_lookup`` (query a source for one generation; read-only, the
  proposal goes in the result), ``source_apply`` (save the values a person accepted from a
  lookup as that source's accepted evidence, published at once) and ``source_update``.

Downgrade deletes the actions and every external value but the template's (the table had room
for one external value per field).

Revision ID: 0017_external_sources
Revises: 0016_vehicle_identity
"""
from __future__ import annotations

from alembic import op

revision = "0017_external_sources"
down_revision = "0016_vehicle_identity"
branch_labels = None
depends_on = None

# Frozen here (never imported from live code), like every migration's values.
CAPTURE = "captura"
BEFORE = ("decide_case", "set_value", "split_generation", "merge_generations", "add_evolution_note",
          "catalog_upsert", "user_upsert", "recalculate", "export_specs", "import_specs")
AFTER = BEFORE + ("source_lookup", "source_apply", "source_update")
SOURCES = [
    # code, name, url, credit, provides, priority
    ("vpic_canada", "vPIC (NHTSA): especificaciones canadienses",
     "https://vpic.nhtsa.dot.gov/api/", "NHTSA vPIC, Canadian Vehicle Specifications",
     "Largo, ancho, alto y distancia entre ejes de la generación, por marca, modelo y año", 10),
    ("fueleconomy", "fueleconomy.gov (EPA / DOE)",
     "https://www.fueleconomy.gov/feg/ws/index.shtml", "Courtesy of FuelEconomy.gov, U.S. Dept. of Energy",
     "Consumo combinado, cilindros, velocidades y autonomía eléctrica de cada tren motriz, por año", 20),
]


def _kinds(values) -> str:
    listed = ", ".join(f"'{v}'" for v in values)
    return f"ALTER TABLE kb.web_action ADD CONSTRAINT web_action_kind_check CHECK (kind IN ({listed}))"


def upgrade() -> None:
    op.execute("""
CREATE TABLE kb.external_source (
    code text PRIMARY KEY CHECK (code ~ '^[a-z0-9_]+$' AND code <> 'captura'),
    name text NOT NULL,
    url text NOT NULL,
    credit text NOT NULL,
    provides text NOT NULL,
    paid boolean NOT NULL DEFAULT false,
    active boolean NOT NULL DEFAULT true,
    countries text[] NOT NULL DEFAULT '{US}',
    priority integer NOT NULL DEFAULT 100 CHECK (priority BETWEEN 1 AND 1000),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text
)""")
    op.execute("COMMENT ON TABLE kb.external_source IS "
               "'Fuentes externas automáticas: a qué países aplican (vacío = todos), si están activas, si son de pago "
               "y su prioridad (menor primero; lo capturado en la plantilla siempre gana)'")
    for code, name, url, credit, provides, priority in SOURCES:
        op.execute(f"INSERT INTO kb.external_source (code, name, url, credit, provides, priority) VALUES "
                   f"('{code}', '{name}', '{url}', '{credit}', '{provides}', {priority})")

    op.execute("ALTER TABLE kb.spec_evidence ADD COLUMN source_code text NOT NULL DEFAULT ''")
    op.execute(f"UPDATE kb.spec_evidence SET source_code = '{CAPTURE}' WHERE source_kind = 'external'")
    op.execute("ALTER TABLE kb.spec_evidence ADD CONSTRAINT spec_evidence_source_code_check "
               "CHECK ((source_kind = 'external') = (source_code <> ''))")
    op.execute("ALTER TABLE kb.spec_evidence DROP CONSTRAINT spec_evidence_entity_type_entity_id_field_source_kind_key")
    op.execute("ALTER TABLE kb.spec_evidence ADD CONSTRAINT spec_evidence_key "
               "UNIQUE (entity_type, entity_id, field, source_kind, source_code)")
    op.execute("COMMENT ON COLUMN kb.spec_evidence.source_code IS "
               "'Fuente de un valor externo: captura (la plantilla) o un código de kb.external_source; vacío en los demás'")

    op.execute("ALTER TABLE kb.web_action DROP CONSTRAINT web_action_kind_check")
    op.execute(_kinds(AFTER))


def downgrade() -> None:
    op.execute("DELETE FROM kb.web_action WHERE kind IN ('source_lookup', 'source_apply', 'source_update')")
    op.execute("ALTER TABLE kb.web_action DROP CONSTRAINT web_action_kind_check")
    op.execute(_kinds(BEFORE))
    op.execute(f"DELETE FROM kb.spec_evidence WHERE source_kind = 'external' AND source_code <> '{CAPTURE}'")
    op.execute("ALTER TABLE kb.spec_evidence DROP CONSTRAINT spec_evidence_key")
    op.execute("ALTER TABLE kb.spec_evidence DROP CONSTRAINT spec_evidence_source_code_check")
    op.execute("ALTER TABLE kb.spec_evidence DROP COLUMN source_code")
    op.execute("ALTER TABLE kb.spec_evidence ADD CONSTRAINT spec_evidence_entity_type_entity_id_field_source_kind_key "
               "UNIQUE (entity_type, entity_id, field, source_kind)")
    op.execute("DROP TABLE kb.external_source")
