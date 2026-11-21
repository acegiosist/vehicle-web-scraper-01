"""Review queue: which cases carry an AI proposal (from_ai, ai_run_id).

Revision ID: 0004_queue_ai_origin
Revises: 0003_web_jobs
Create Date: 2026-11-21

`kb.review_queue` gains two columns at the end (CREATE OR REPLACE keeps the website role's
grants): `from_ai` (the case's proposal came from a Claude batch) and `ai_run_id`.

Also repairs `review_item.source`: before this revision `normalize` re-opened an AI case with
source 'rule' (identity.open_review now keeps it), so collected cases lost their origin after
the first recalculation. `ai_decision_id` was always kept, so the origin can be restored.
"""
from alembic import op

revision = "0004_queue_ai_origin"
down_revision = "0003_web_jobs"
branch_labels = None
depends_on = None

# Same SELECT as 0002_review_web, with {extra_columns} / {extra_joins} for this revision.
VIEW = """
CREATE {replace} VIEW kb.review_queue AS
SELECT r.id, r.level, r.kind, r.review_batch_id, r.entity_type, r.entity_id, r.country, r.field, r.issue,
       r.proposed, r.current, r.evidence, r.source, r.listings_affected, r.status, r.corrected_value,
       r.reviewer, r.decided_at, r.note, r.created_at, r.evidence_id, r.ai_decision_id,
       (r.kind = 'individual' OR r.note = 'IN SAMPLE' OR r.issue = 'ai_value_sample') AS in_queue,
       mk.id AS make_id, mk.name AS make_name, md.id AS model_id, md.name AS model_name,
       v.id AS variant_id, md.vehicle_class,
       CASE r.entity_type
           WHEN 'make' THEN mk.name
           WHEN 'model' THEN mk.name || ' / ' || md.name
           WHEN 'trim' THEN mk.name || ' / ' || md.name || ' / ' || t.name
           WHEN 'listing' THEN concat_ws(' ', l.source_site || ':' || l.listing_id, l.raw_make, l.raw_model, l.raw_year)
           ELSE concat_ws(' ', mk.name, md.name, vt.name, v.model_year,
                          trim_scale(v.engine_displacement_l)::text || ' L',
                          v.fuel_type, v.transmission_type, v.drivetrain)
       END AS entity_label,
       q.id AS queued_decision_id{extra_columns}
FROM kb.review_item r
LEFT JOIN kb.trim t ON r.entity_type = 'trim' AND t.id = r.entity_id
LEFT JOIN kb.variant v ON r.entity_type IN ('variant', 'spec') AND v.id = r.entity_id
LEFT JOIN kb.trim vt ON vt.id = v.trim_id
LEFT JOIN kb.listing l ON r.entity_type = 'listing'
                      AND kb.listing_number(l.source_site, l.listing_id) = r.entity_id
LEFT JOIN kb.model md ON md.id = CASE r.entity_type WHEN 'model' THEN r.entity_id
                                                    ELSE coalesce(t.model_id, v.model_id, l.model_id) END
LEFT JOIN kb.make mk ON mk.id = CASE r.entity_type WHEN 'make' THEN r.entity_id
                                                   ELSE coalesce(md.make_id, l.make_id) END
LEFT JOIN kb.review_decision q ON q.review_item_id = r.id AND q.status = 'queued'{extra_joins};
"""


def upgrade() -> None:
    op.execute(VIEW.format(
        replace="OR REPLACE",
        extra_columns=",\n       (r.ai_decision_id IS NOT NULL) AS from_ai, d.ai_run_id",
        extra_joins="\nLEFT JOIN kb.ai_decision d ON d.id = r.ai_decision_id"))
    op.execute("COMMENT ON VIEW kb.review_queue IS 'Review cases with a readable label, make/model, "
               "in_queue, the queued decision and the AI origin (from_ai, ai_run_id).'")
    op.execute("UPDATE kb.review_item SET source = 'ai' WHERE ai_decision_id IS NOT NULL AND source = 'rule'")


def downgrade() -> None:
    # a view cannot lose columns with CREATE OR REPLACE. The website role gets SELECT back from
    # the schema's default privileges; re-run docs/sql/review_web_grants.sql to be sure.
    op.execute("DROP VIEW kb.review_queue")
    op.execute(VIEW.format(replace="", extra_columns="", extra_joins=""))
