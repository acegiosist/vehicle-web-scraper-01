-- Privileges of the review website's role (kb_review_web). Safe to re-run: run it again after
-- every migration, as the owner that runs the Alembic migrations.
--   psql "postgresql://OWNER@HOST:PORT/DB" -f docs/sql/review_web_grants.sql
-- Without psql on Windows, through the Postgres container:
--   Get-Content docs\sql\review_web_grants.sql | docker exec -i CONTAINER psql -U OWNER -d DB -v ON_ERROR_STOP=1
--
-- The site reads the knowledge base and can only INSERT decisions and jobs; the Python worker
-- (`vehicle-scraper kb worker`, with the owner's KB_DATABASE_URL) applies and runs them.

GRANT USAGE ON SCHEMA kb, staging TO kb_review_web;
GRANT SELECT ON ALL TABLES IN SCHEMA kb TO kb_review_web;          -- tables and views
GRANT SELECT ON staging.raw_listing TO kb_review_web;               -- listing text shown as evidence
-- tables added by later migrations (created by this same owner) are readable too
ALTER DEFAULT PRIVILEGES IN SCHEMA kb GRANT SELECT ON TABLES TO kb_review_web;

-- queue a decision (migration 0002): status, error and dates stay under the worker's control
GRANT INSERT (review_item_id, decision, corrected_value, note, reviewer) ON kb.review_decision TO kb_review_web;
GRANT USAGE ON SEQUENCE kb.review_decision_id_seq TO kb_review_web;

-- queue a job and cancel one that has not started (migration 0003)
GRANT INSERT (command, params, requested_by) ON kb.job TO kb_review_web;
GRANT USAGE ON SEQUENCE kb.job_id_seq TO kb_review_web;
GRANT EXECUTE ON FUNCTION kb.cancel_job(bigint) TO kb_review_web;
