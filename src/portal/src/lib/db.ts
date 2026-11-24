import "server-only";

import { Kysely, PostgresDialect } from "kysely";
import { Pool, types } from "pg";
import { z } from "zod";

import type { DB } from "@/generated/db";

const urlSchema = z
  .string({ error: "Falta PORTAL_DATABASE_URL (ver .env.example)" })
  .regex(/^postgres(ql)?:\/\//, "PORTAL_DATABASE_URL debe ser una URL postgresql://");

function createDb(): Kysely<DB> {
  // numeric (displacement, tank) as a JS number, matching the generated types (--numeric-parser number).
  // bigint ids stay strings: they are only compared and put in URLs.
  types.setTypeParser(types.builtins.NUMERIC, (v) => Number.parseFloat(v));
  const pool = new Pool({
    // The portal's role (docs/sql/portal_role.sql) can only read and INSERT into kb.web_action.
    connectionString: urlSchema.parse(process.env.PORTAL_DATABASE_URL),
    max: 5,
    idleTimeoutMillis: 30_000,
    connectionTimeoutMillis: 5_000,
    // a slow query must not hang a page; the portal never runs long statements
    statement_timeout: 10_000,
    application_name: "omnibase-portal",
  });
  return new Kysely<DB>({ dialect: new PostgresDialect({ pool }) });
}

// One pool per server process, created on first use (so `next build` needs no database),
// and not one per hot reload in development.
const globalForDb = globalThis as unknown as { omnibasePortalDb?: Kysely<DB> };

export function getDb(): Kysely<DB> {
  globalForDb.omnibasePortalDb ??= createDb();
  return globalForDb.omnibasePortalDb;
}
