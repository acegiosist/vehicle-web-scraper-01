"""Jobs the review website can queue (recalculate, export, AI estimate/collect/submit).

Revision ID: 0003_web_jobs
Revises: 0002_review_web
Create Date: 2026-11-21

Same pattern as kb.review_decision: the site only INSERTs a job; the Python worker
(`vehicle-scraper kb worker`) runs it with the CLI's own code (kb/commands.py). The site
never runs processes and never holds the Anthropic API key.
"""
from alembic import op

revision = "0003_web_jobs"
down_revision = "0002_review_web"
branch_labels = None
depends_on = None

CHANNEL = "kb_job"
COMMANDS = ["normalize", "consolidate", "recalculate", "export", "ai_estimate", "ai_collect", "ai_submit"]


def upgrade() -> None:
    commands = ", ".join(f"'{c}'" for c in COMMANDS)
    op.execute(f"""
CREATE TABLE kb.job (
    id bigserial PRIMARY KEY,
    command text NOT NULL CHECK (command IN ({commands})),
    params jsonb NOT NULL DEFAULT '{{}}'::jsonb CHECK (jsonb_typeof(params) = 'object'),
    requested_by text NOT NULL CHECK (length(btrim(requested_by)) BETWEEN 1 AND 100),
    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'failed', 'canceled')),
    summary text,
    result jsonb,
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz
);
COMMENT ON TABLE kb.job IS
    'kb commands queued by the review website; run by `kb worker` with kb/commands.py. Also the audit trail.';
-- the same job cannot be queued twice while one is waiting or running
CREATE UNIQUE INDEX job_active ON kb.job (command, params) WHERE status IN ('queued', 'running');
CREATE INDEX job_status ON kb.job (status, id);

CREATE TABLE kb.job_file (
    job_id bigint PRIMARY KEY REFERENCES kb.job(id) ON DELETE CASCADE,
    filename text NOT NULL,
    content_type text NOT NULL,
    gzipped boolean NOT NULL,
    size bigint NOT NULL,
    bytes bytea NOT NULL
);
COMMENT ON TABLE kb.job_file IS 'Files produced by jobs (exports). Only the latest ones are kept.';

CREATE FUNCTION kb.notify_job() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify('{CHANNEL}', NEW.id::text);
    RETURN NEW;
END $$;
CREATE TRIGGER job_notify AFTER INSERT ON kb.job FOR EACH ROW EXECUTE FUNCTION kb.notify_job();

-- The only change the website may make to a job: cancel one that has not started.
CREATE FUNCTION kb.cancel_job(job_id bigint) RETURNS boolean
    LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, kb
    AS $$ UPDATE kb.job SET status = 'canceled', finished_at = now()
          WHERE id = job_id AND status = 'queued' RETURNING true $$;
REVOKE ALL ON FUNCTION kb.cancel_job(bigint) FROM PUBLIC;
""")


def downgrade() -> None:
    op.execute("""
DROP FUNCTION kb.cancel_job(bigint);
DROP TRIGGER job_notify ON kb.job;
DROP FUNCTION kb.notify_job();
DROP TABLE kb.job_file;
DROP TABLE kb.job;
""")
