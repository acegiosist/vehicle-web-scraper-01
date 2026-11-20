import "server-only";

import { Kysely, PostgresDialect } from "kysely";
import { Pool, types } from "pg";
import { z } from "zod";

import type { DB } from "@/generated/db";

const urlSchema = z
  .string({ error: "Falta REVIEW_WEB_DATABASE_URL (ver .env.example)" })
  .regex(/^postgres(ql)?:\/\//, "REVIEW_WEB_DATABASE_URL debe ser una URL postgresql://");

function createDb(): Kysely<DB> {
  // numeric (displacement) as a JS number, matching the generated types (--numeric-parser number).
  // bigint ids stay strings: they are only compared and put in URLs.
  types.setTypeParser(types.builtins.NUMERIC, (v) => Number.parseFloat(v));
  const pool = new Pool({
    connectionString: urlSchema.parse(process.env.REVIEW_WEB_DATABASE_URL),
    max: 5,
    idleTimeoutMillis: 30_000,
    connectionTimeoutMillis: 5_000,
    // a slow query must not hang a page; the site never runs long statements
    statement_timeout: 10_000,
    application_name: "kb-review-web",
  });
  return new Kysely<DB>({ dialect: new PostgresDialect({ pool }) });
}

// One pool per server process, created on first use (so `next build` needs no database),
// and not one per hot reload in development.
const globalForDb = globalThis as unknown as { kbReviewDb?: Kysely<DB> };

export function getDb(): Kysely<DB> {
  globalForDb.kbReviewDb ??= createDb();
  return globalForDb.kbReviewDb;
}
