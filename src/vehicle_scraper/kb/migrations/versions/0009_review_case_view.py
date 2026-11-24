"""``kb.review_case``: each review case with a readable entity label, its make and a link.

``review_item.entity_key`` points at a make, model, listing ("site:id"), generation,
powertrain or variant; this view resolves it once, so the portal and the Excel export show the
same text. After this migration re-run ``docs/sql/portal_role.sql`` (the portal reads the view).

Revision ID: 0009_review_case_view
Revises: 0008_first_editor
"""
from __future__ import annotations

from alembic import op

revision = "0009_review_case_view"
down_revision = "0008_first_editor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE VIEW kb.review_case AS
SELECT r.id, r.issue, r.entity_type, r.entity_key, r.field, r.current_value, r.proposed_value, r.evidence,
       r.listings_affected, r.status, r.corrected_value, r.decided_by, r.decided_at, r.note, r.created_at,
       r.updated_at,
       coalesce(k.name, mk.name, lk.name, gk.name, pk.name, vk.name, s.data->>'make') AS make_name,
       CASE r.entity_type
           WHEN 'make' THEN k.name
           WHEN 'model' THEN mk.name || ' ' || m.name
           WHEN 'listing' THEN concat_ws(' ', s.data->>'make', s.data->>'model', s.data->>'trim',
                                         s.data->>'model_year', '(' || r.entity_key || ')')
           WHEN 'generation' THEN gk.name || ' ' || g.name || ' ' || coalesce(g.observed_year_from::text, '?')
                                  || '-' || coalesce(g.observed_year_to::text, '?')
           WHEN 'powertrain' THEN pk.name || ' ' || pg.name || ' / ' || p.match_key
           WHEN 'variant' THEN vk.name || ' ' || vg.name || ' / ' || vp.match_key || ' / ' || v.country_code
                               || ' / ' || coalesce(v.trim_name, '(sin versión)')
       END AS entity_label,
       s.data->>'source_url' AS link,
       coalesce(src.country_code, v.country_code) AS country_code
FROM kb.review_item r
LEFT JOIN kb.make k ON r.entity_type = 'make' AND k.id::text = r.entity_key
LEFT JOIN kb.model m ON r.entity_type = 'model' AND m.id::text = r.entity_key
LEFT JOIN kb.make mk ON mk.id = m.make_id
LEFT JOIN staging.raw_listing s ON r.entity_type = 'listing' AND s.valid_to IS NULL
      AND s.source_site = split_part(r.entity_key, ':', 1)
      AND s.listing_id = substr(r.entity_key, strpos(r.entity_key, ':') + 1)
LEFT JOIN kb.source_site src ON src.code = s.source_site
LEFT JOIN kb.clean_listing cl ON cl.source_site = s.source_site AND cl.listing_id = s.listing_id
LEFT JOIN kb.make lk ON lk.id = cl.make_id
LEFT JOIN kb.generation g ON r.entity_type = 'generation' AND g.id::text = r.entity_key
LEFT JOIN kb.model gm ON gm.id = g.model_id
LEFT JOIN kb.make gk ON gk.id = gm.make_id
LEFT JOIN kb.powertrain p ON r.entity_type = 'powertrain' AND p.id::text = r.entity_key
LEFT JOIN kb.generation pg ON pg.id = p.generation_id
LEFT JOIN kb.model pm ON pm.id = pg.model_id
LEFT JOIN kb.make pk ON pk.id = pm.make_id
LEFT JOIN kb.commercial_variant v ON r.entity_type = 'variant' AND v.id::text = r.entity_key
LEFT JOIN kb.generation vg ON vg.id = v.generation_id
LEFT JOIN kb.powertrain vp ON vp.id = v.powertrain_id
LEFT JOIN kb.model vm ON vm.id = vg.model_id
LEFT JOIN kb.make vk ON vk.id = vm.make_id""")
    op.execute("COMMENT ON VIEW kb.review_case IS "
               "'Casos de revisión con la entidad legible (marca, modelo, anuncio, generación...) y su enlace'")


def downgrade() -> None:
    op.execute("DROP VIEW kb.review_case")
