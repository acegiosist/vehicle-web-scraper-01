-- Database role for the portal (src/portal): read everything, write only requests.
--
-- Run as the owner of omnibase after `kb migrate`, and again after every new migration
-- (it only grants; it never drops anything). The role is created once, by you:
--
--   CREATE ROLE omnibase_portal LOGIN PASSWORD '<a strong password>';
--
-- Then point the portal at it (src/portal/.env.local):
--   PORTAL_DATABASE_URL=postgresql://omnibase_portal:<password>@localhost:5435/omnibase
--
-- What the portal can do with this role:
--   * SELECT every table and view in the kb and staging schemas;
--   * INSERT into kb.web_action, only the kind, payload and requested_by columns, so it can't
--     mark its own request as applied. The kb worker (owner role) applies the requests.
-- Nothing else: no UPDATE, DELETE or INSERT anywhere else.

GRANT CONNECT ON DATABASE omnibase TO omnibase_portal;
GRANT USAGE ON SCHEMA kb, staging TO omnibase_portal;
GRANT SELECT ON ALL TABLES IN SCHEMA kb, staging TO omnibase_portal;
GRANT INSERT (kind, payload, requested_by) ON kb.web_action TO omnibase_portal;

-- Tables and views that future migrations create get SELECT automatically. Default privileges
-- apply only to objects created by the role that runs this ALTER (the owner, who also runs the
-- migrations), so run this script as that same role. Without this, a new view such as
-- kb.review_case fails with "permission denied" until the GRANT above is run again.
ALTER DEFAULT PRIVILEGES IN SCHEMA kb, staging GRANT SELECT ON TABLES TO omnibase_portal;
