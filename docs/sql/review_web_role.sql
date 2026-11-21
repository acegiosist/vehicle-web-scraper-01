-- Least-privilege role for the review website (src/web). Run once per database cluster,
-- then run review_web_grants.sql (and again after every migration).
--
--   psql "postgresql://OWNER@HOST:PORT/DB" -v pw='a-strong-password' -f docs/sql/review_web_role.sql
--   psql "postgresql://OWNER@HOST:PORT/DB" -f docs/sql/review_web_grants.sql
-- Without psql on Windows, through the Postgres container:
--   Get-Content docs\sql\review_web_role.sql | docker exec -i CONTAINER psql -U OWNER -d DB -v ON_ERROR_STOP=1 -v pw='a-strong-password'
--
-- Then put in src/web/.env.local:
--   REVIEW_WEB_DATABASE_URL=postgresql://kb_review_web:a-strong-password@HOST:PORT/DB

CREATE ROLE kb_review_web LOGIN PASSWORD :'pw';
ALTER ROLE kb_review_web SET statement_timeout = '10s';
