-- Least-privilege role for the review website (src/web).
--
-- The site reads the knowledge base and can only INSERT decisions into kb.review_decision;
-- the Python worker (`vehicle-scraper kb review worker`, with the owner's KB_DATABASE_URL)
-- applies them. Even a bug in the site cannot change sheets, identities or evidence.
--
-- Run once per database, as the owner that runs the Alembic migrations, after migration 0002:
--   psql "postgresql://OWNER@HOST:PORT/DB" -v pw='a-strong-password' -f docs/sql/review_web_role.sql
-- Then put in src/web/.env.local:
--   REVIEW_WEB_DATABASE_URL=postgresql://kb_review_web:a-strong-password@HOST:PORT/DB

CREATE ROLE kb_review_web LOGIN PASSWORD :'pw';
ALTER ROLE kb_review_web SET statement_timeout = '10s';

GRANT USAGE ON SCHEMA kb, staging TO kb_review_web;
GRANT SELECT ON ALL TABLES IN SCHEMA kb TO kb_review_web;          -- tables and views
GRANT SELECT ON staging.raw_listing TO kb_review_web;               -- listing text shown as evidence
-- tables added by later migrations (created by this same owner) are readable too
ALTER DEFAULT PRIVILEGES IN SCHEMA kb GRANT SELECT ON TABLES TO kb_review_web;

-- the only write: queue a decision (status, error and dates stay under the worker's control)
GRANT INSERT (review_item_id, decision, corrected_value, note, reviewer) ON kb.review_decision TO kb_review_web;
GRANT USAGE ON SEQUENCE kb.review_decision_id_seq TO kb_review_web;
