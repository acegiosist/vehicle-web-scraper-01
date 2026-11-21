import "server-only";

import { sql } from "kysely";
import { io } from "next/cache";

import { getDb } from "@/lib/db";
import { FIELDS } from "@/lib/fields";

// The same numbers as `vehicle-scraper kb status` (src/vehicle_scraper/kb/export.py), read-only.

export async function identityCounts() {
  await io();
  const db = getDb();
  const count = (table: "kb.make" | "kb.model" | "kb.trim") =>
    db
      .selectFrom(table)
      .select((eb) => ["status", eb.fn.countAll<string>().as("n")])
      .groupBy("status")
      .orderBy("status")
      .execute();
  const [make, model, trim] = await Promise.all([count("kb.make"), count("kb.model"), count("kb.trim")]);
  const shape = (rows: { status: string; n: string }[]) => Object.fromEntries(rows.map((r) => [r.status, Number(r.n)]));
  return { make: shape(make), model: shape(model), trim: shape(trim) };
}

export async function totals() {
  await io();
  const row = await sql<{
    listings: string;
    matched: string;
    variants: string;
    mech: string;
    equip: string;
    pending: string;
  }>`select (select count(*) from kb.listing) as listings,
            (select count(variant_id) from kb.listing) as matched,
            (select count(*) from kb.variant) as variants,
            (select count(*) from kb.variant_spec) as mech,
            (select count(*) from kb.variant_market_spec) as equip,
            (select count(*) from kb.review_item where status = 'pending') as pending`
    .execute(getDb())
    .then((r) => r.rows[0]);
  return Object.fromEntries(Object.entries(row).map(([k, v]) => [k, Number(v)])) as Record<keyof typeof row, number>;
}

export async function reviewSummary() {
  await io();
  const rows = await getDb()
    .selectFrom("kb.review_item")
    .select((eb) => [
      "level",
      "kind",
      "issue",
      eb.fn.countAll<string>().as("n"),
      eb.fn.sum<string | null>("listings_affected").as("listings"),
    ])
    .where("status", "=", "pending")
    .groupBy(["level", "kind", "issue"])
    .orderBy("level")
    .orderBy("kind")
    .orderBy(sql`count(*)`, "desc")
    .execute();
  return rows.map((r) => ({ ...r, n: Number(r.n), listings: Number(r.listings ?? 0) }));
}

/** % of matched listings with each mechanical / equipment field filled (after the knowledge base). */
export async function coverage() {
  await io();
  const fields = Object.entries(FIELDS)
    .filter(([, f]) => f.group !== "key")
    .map(([name, f]) => ({ name, group: f.group }));
  // column names come from the field catalog, never from the request
  const counts = sql.join(fields.map((f) => sql`count(${sql.ref(f.name)}) as ${sql.ref(f.name)}`));
  const row = await sql<Record<string, string>>`select count(*) as total, ${counts}
      from kb.listing_standardized where variant_id is not null`
    .execute(getDb())
    .then((r) => r.rows[0]);
  const total = Number(row.total);
  return {
    total,
    fields: fields.map((f) => ({ ...f, pct: total ? (100 * Number(row[f.name])) / total : 0 })),
  };
}

export async function aiRuns() {
  await io();
  const rows = await getDb()
    .selectFrom("kb.ai_run")
    .select((eb) => [
      "kind",
      "status",
      eb.fn.countAll<string>().as("runs"),
      eb.fn.sum<string | null>("request_count").as("requests"),
      eb.fn.sum<number | null>("est_cost_usd").as("usd"),
      eb.fn.sum<number | null>("actual_cost_usd").as("actual_usd"),
    ])
    .groupBy(["kind", "status"])
    .orderBy("kind")
    .execute();
  return rows.map((r) => ({
    ...r,
    runs: Number(r.runs),
    requests: Number(r.requests ?? 0),
    usd: Number(r.usd ?? 0),
    actualUsd: r.actual_usd === null ? null : Number(r.actual_usd),
  }));
}
