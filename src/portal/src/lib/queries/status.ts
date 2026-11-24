import "server-only";

import { sql } from "kysely";
import { io } from "next/cache";

import { getDb } from "@/lib/db";

/** Headline numbers of the knowledge base (the same sources as `vehicle_scraper kb status`). */
export async function totals() {
  await io();
  const row = await sql<{
    listings: string;
    in_scope: string;
    assigned: string;
    generations: string;
    powertrains: string;
    variants: string;
    pending_cases: string;
  }>`select (select count(*) from staging.raw_listing where valid_to is null) as listings,
            (select count(*) from kb.clean_listing where excluded_reason is null) as in_scope,
            (select count(*) from kb.listing_level where variant_id is not null) as assigned,
            (select count(*) from kb.generation where listings > 0) as generations,
            (select count(*) from kb.powertrain where listings > 0) as powertrains,
            (select count(*) from kb.commercial_variant where listings > 0) as variants,
            (select count(*) from kb.review_item where status = 'pending') as pending_cases`.execute(getDb());
  const r = row.rows[0];
  return Object.fromEntries(Object.entries(r).map(([k, v]) => [k, Number(v)])) as Record<keyof typeof r, number>;
}

/** Applied portal changes since the last recalculation (what "Recalcular" would bring in). */
export async function pendingRecalc() {
  await io();
  const db = getDb();
  const last = await db
    .selectFrom("kb.web_action")
    .select(["applied_at", "status"])
    .where("kind", "=", "recalculate")
    .where("status", "in", ["applied", "running"])
    .orderBy("id", "desc")
    .executeTakeFirst();
  let q = db
    .selectFrom("kb.web_action")
    .select((eb) => eb.fn.countAll<string>().as("n"))
    .where("kind", "!=", "recalculate")
    .where("status", "=", "applied");
  if (last?.applied_at) q = q.where("applied_at", ">", last.applied_at);
  const [{ n }, queued] = await Promise.all([
    q.executeTakeFirstOrThrow(),
    db.selectFrom("kb.web_action").select("id").where("kind", "=", "recalculate").where("status", "=", "queued")
      .executeTakeFirst(),
  ]);
  return {
    changes: Number(n),
    lastRecalc: last?.applied_at ?? null,
    running: last?.status === "running",
    queued: !!queued,
  };
}
