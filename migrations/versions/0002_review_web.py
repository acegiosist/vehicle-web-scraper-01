"""Review website: decision inbox, queue view, listing number function.

Revision ID: 0002_review_web
Revises: 0001_kb_schema
Create Date: 2026-11-20

The review website (src/web) only INSERTs rows into ``kb.review_decision``; the Python worker
(`vehicle-scraper kb review worker`) applies them with the same code as `kb review import`.
An AFTER INSERT trigger NOTIFYs the worker so a decision is applied within a second.
"""
from alembic import op

revision = "0002_review_web"
down_revision = "0001_kb_schema"
branch_labels = None
depends_on = None

CHANNEL = "kb_review_decision"


def upgrade() -> None:
    op.execute(f"""
-- Same number as identity.listing_number() in Python: review_item.entity_id of a listing.
-- (sha256: Postgres has no built-in sha1; listing cases from 0001 are renumbered below.)
CREATE FUNCTION kb.listing_number(site text, listing_id text) RETURNS bigint
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    AS $$ SELECT ('x' || substr(encode(sha256(convert_to(site || '|' || listing_id, 'UTF8')), 'hex'), 1, 15))
                 ::bit(60)::bigint $$;
CREATE INDEX listing_number_idx ON kb.listing (kb.listing_number(source_site, listing_id));

CREATE TABLE kb.review_decision (
    id bigserial PRIMARY KEY,
    review_item_id bigint NOT NULL REFERENCES kb.review_item(id) ON DELETE CASCADE,
    decision text NOT NULL CHECK (decision IN ('approved', 'rejected', 'corrected')),
    corrected_value text CHECK (length(corrected_value) <= 500),
    note text CHECK (length(note) <= 2000),
    reviewer text NOT NULL CHECK (length(btrim(reviewer)) BETWEEN 1 AND 100),
    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'applied', 'failed', 'superseded')),
    error text,
    submitted_at timestamptz NOT NULL DEFAULT now(),
    processed_at timestamptz,
    CHECK (decision <> 'corrected' OR nullif(btrim(corrected_value), '') IS NOT NULL)
);
COMMENT ON TABLE kb.review_decision IS
    'Inbox of decisions from the review website; applied by `kb review worker`. Also the audit trail.';
-- one waiting decision per case: a double click or a second reviewer cannot queue it twice
CREATE UNIQUE INDEX review_decision_queued ON kb.review_decision (review_item_id) WHERE status = 'queued';
CREATE INDEX review_decision_status ON kb.review_decision (status, id);
CREATE INDEX review_decision_item ON kb.review_decision (review_item_id);

CREATE FUNCTION kb.notify_review_decision() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify('{CHANNEL}', NEW.id::text);
    RETURN NEW;
END $$;
CREATE TRIGGER review_decision_notify AFTER INSERT ON kb.review_decision
    FOR EACH ROW EXECUTE FUNCTION kb.notify_review_decision();

-- Every review case with a readable label and the make/model it belongs to (for filters).
-- in_queue = what `kb review export` would export: individual cases and the sampled ones.
CREATE VIEW kb.review_queue AS
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
       q.id AS queued_decision_id
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
LEFT JOIN kb.review_decision q ON q.review_item_id = r.id AND q.status = 'queued';
""")
    _renumber_listing_cases(old="sha1", new="sha256")


def _renumber_listing_cases(old: str, new: str) -> None:
    """Listing review cases were numbered with sha1 before this revision (and are again after
    a downgrade): recompute their entity_id in Python, the only place both hashes exist."""
    import hashlib

    from sqlalchemy import text

    bind = op.get_bind()
    if not bind.execute(text("SELECT 1 FROM kb.review_item WHERE entity_type = 'listing' LIMIT 1")).first():
        return

    def number(algo: str, site: str, listing_id: str) -> int:
        return int(hashlib.new(algo, f"{site}|{listing_id}".encode()).hexdigest()[:15], 16)

    remap = {number(old, s, i): number(new, s, i)
             for s, i in bind.execute(text("SELECT source_site, listing_id FROM kb.listing"))}
    for item_id, entity_id in bind.execute(text("SELECT id, entity_id FROM kb.review_item "
                                                "WHERE entity_type = 'listing'")).all():
        if entity_id in remap:
            bind.execute(text("UPDATE kb.review_item SET entity_id = :n WHERE id = :id"),
                         {"n": remap[entity_id], "id": item_id})


def downgrade() -> None:
    _renumber_listing_cases(old="sha256", new="sha1")
    op.execute("""
DROP VIEW kb.review_queue;
DROP TRIGGER review_decision_notify ON kb.review_decision;
DROP FUNCTION kb.notify_review_decision();
DROP TABLE kb.review_decision;
DROP INDEX kb.listing_number_idx;
DROP FUNCTION kb.listing_number(text, text);
""")
