import "server-only";

import { sql } from "kysely";
import { io } from "next/cache";

import { getDb } from "@/lib/db";
import { isIssue, type Issue } from "@/lib/issues";

export const QUEUE_PAGE_SIZE = 50;

export interface QueueFilters {
  issue?: Issue;
  q?: string;
  page: number;
}

export function parseQueueFilters(sp: Record<string, string | string[] | undefined>): QueueFilters {
  const one = (k: string) => (Array.isArray(sp[k]) ? sp[k][0] : sp[k]);
  const issue = one("tipo");
  const page = Number.parseInt(one("pagina") ?? "1", 10);
  const q = (one("q") ?? "").trim().slice(0, 80);
  return { issue: isIssue(issue) ? issue : undefined, q: q || undefined, page: page > 0 ? page : 1 };
}

export function queueHref(f: QueueFilters, page = f.page): string {
  const p = new URLSearchParams();
  if (f.issue) p.set("tipo", f.issue);
  if (f.q) p.set("q", f.q);
  if (page > 1) p.set("pagina", String(page));
  const s = p.toString();
  return s ? `/revision?${s}` : "/revision";
}

/** Pending cases per issue. */
export async function pendingByIssue() {
  await io();
  const rows = await getDb()
    .selectFrom("kb.review_item")
    .select((eb) => ["issue", eb.fn.countAll<string>().as("n"), eb.fn.sum<string>("listings_affected").as("listings")])
    .where("status", "=", "pending")
    .groupBy("issue")
    .execute();
  return Object.fromEntries(rows.map((r) => [r.issue, { cases: Number(r.n), listings: Number(r.listings) }]));
}

export async function reviewQueue(f: QueueFilters) {
  await io();
  let q = getDb().selectFrom("kb.review_case").where("status", "=", "pending");
  if (f.issue) q = q.where("issue", "=", f.issue);
  if (f.q) {
    const like = `%${f.q.replace(/[\\%_]/g, (m) => `\\${m}`)}%`;
    q = q.where((eb) => eb.or([eb("entity_label", "ilike", like), eb("make_name", "ilike", like)]));
  }
  const [rows, total] = await Promise.all([
    q
      .select(["id", "issue", "entity_type", "entity_label", "field", "current_value", "proposed_value",
               "listings_affected", "country_code"])
      .orderBy("listings_affected", "desc")
      .orderBy("id")
      .limit(QUEUE_PAGE_SIZE)
      .offset((f.page - 1) * QUEUE_PAGE_SIZE)
      .execute(),
    q.select((eb) => eb.fn.countAll<string>().as("n")).executeTakeFirstOrThrow(),
  ]);
  return { rows, total: Number(total.n) };
}

export async function getCase(id: string) {
  await io();
  if (!/^\d+$/.test(id)) return null;
  const db = getDb();
  // Requests first, then the case (see recentActionsFor): a request read as applied means its
  // decision is already committed, so the case read next can't show it pending.
  const requests = await db
    .selectFrom("kb.web_action")
    .select(["id", "status", "error", "requested_by", "requested_at", "applied_at", "payload"])
    .where("kind", "=", "decide_case")
    .where(sql<boolean>`payload->>'case_id' = ${id}`)
    .orderBy("id", "desc")
    .limit(10)
    .execute();
  const item = await db.selectFrom("kb.review_case").selectAll().where("id", "=", id).executeTakeFirst();
  if (!item) return null;
  return { item, requests };
}

/** The listing behind a listing case: cleaned values and where it landed. */
export async function caseListing(entityKey: string) {
  await io();
  const sep = entityKey.indexOf(":");
  if (sep < 0) return null;
  const site = entityKey.slice(0, sep);
  const listingId = entityKey.slice(sep + 1);
  return getDb()
    .selectFrom("kb.clean_listing as l")
    .leftJoin("kb.make as k", "k.id", "l.make_id")
    .leftJoin("kb.model as m", "m.id", "l.model_id")
    .leftJoin("kb.listing_level as v", (j) =>
      j.onRef("v.source_site", "=", "l.source_site").onRef("v.listing_id", "=", "l.listing_id"),
    )
    .select([
      "l.source_site", "l.listing_id", "l.country_code", "l.model_year", "l.trim_name", "l.trim_raw",
      "l.body_style_code", "l.fuel_type_code", "l.transmission_type_code", "l.drivetrain_code",
      "l.engine_displacement_l", "l.engine_cylinders", "l.horsepower_hp", "l.excluded_reason", "l.provenance",
      "k.name as make_name", "m.name as model_name", "v.generation_id", "v.variant_id", "v.unassigned_reason",
    ])
    .where("l.source_site", "=", site)
    .where("l.listing_id", "=", listingId)
    .executeTakeFirst();
}

/** One action's status, for the poller. */
export async function actionStatus(id: string) {
  await io();
  if (!/^\d+$/.test(id)) return null;
  return getDb()
    .selectFrom("kb.web_action")
    .select(["id", "kind", "status", "error", "result", "requested_by", "requested_at", "applied_at"])
    .where("id", "=", id)
    .executeTakeFirst();
}
