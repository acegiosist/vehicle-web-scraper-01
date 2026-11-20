import "server-only";

import { type SelectQueryBuilder, sql } from "kysely";
import { io } from "next/cache";

import type { DB } from "@/generated/db";
import { getDb } from "@/lib/db";
import { likePattern, PAGE_SIZE, type QueueFilters } from "@/lib/filters";

type QueueQuery = SelectQueryBuilder<DB, "kb.review_queue", object>;

/** The open queue: what `kb review export` would export (pending, individual or sampled). */
function openQueue() {
  return getDb().selectFrom("kb.review_queue").where("status", "=", "pending").where("in_queue", "=", true);
}

function applyFilters(q: QueueQuery, f: QueueFilters): QueueQuery {
  if (f.level) q = q.where("level", "=", f.level);
  if (f.issue) q = q.where("issue", "=", f.issue);
  if (f.entity) q = q.where("entity_type", "=", f.entity);
  if (f.kind) q = q.where("kind", "=", f.kind);
  if (f.make) q = q.where("make_name", "=", f.make);
  if (f.country) q = q.where("country", "=", f.country);
  if (f.q) {
    const pattern = likePattern(f.q);
    q = q.where((eb) =>
      eb.or([eb("entity_label", "ilike", pattern), eb("field", "ilike", pattern), eb("issue", "ilike", pattern)]),
    );
  }
  return q;
}

/** Same order as `kb review export`: level, individual before sampled, most listings first. */
function reviewOrder<T extends QueueQuery>(q: T) {
  return q
    .orderBy("level")
    .orderBy(sql`kind = 'sample'`)
    .orderBy("listings_affected", "desc")
    .orderBy("id");
}

export async function listQueue(filters: QueueFilters) {
  await io();
  const page = filters.page ?? 1;
  const base = applyFilters(openQueue() as QueueQuery, filters);
  const [rows, total] = await Promise.all([
    reviewOrder(base)
      .select([
        "id",
        "level",
        "kind",
        "entity_type",
        "issue",
        "field",
        "country",
        "entity_label",
        "make_name",
        "listings_affected",
        "queued_decision_id",
        "review_batch_id",
      ])
      .limit(PAGE_SIZE)
      .offset((page - 1) * PAGE_SIZE)
      .execute(),
    base.select((eb) => eb.fn.countAll<string>().as("n")).executeTakeFirstOrThrow(),
  ]);
  return { rows, total: Number(total.n), page, pageCount: Math.max(1, Math.ceil(Number(total.n) / PAGE_SIZE)) };
}

export type QueueRow = Awaited<ReturnType<typeof listQueue>>["rows"][number];

/** Open cases per level, and how many already have a decision waiting for the worker. */
export async function levelCounts() {
  await io();
  const rows = await openQueue()
    .select((eb) => [
      "level",
      eb.fn.countAll<string>().as("open"),
      eb.fn.count<string>("queued_decision_id").as("queued"),
    ])
    .groupBy("level")
    .orderBy("level")
    .execute();
  return rows.map((r) => ({ level: r.level ?? 0, open: Number(r.open), queued: Number(r.queued) }));
}

/** Values for the filter selects (only what is actually in the open queue). */
export async function filterOptions() {
  await io();
  const [issues, makes, countries] = await Promise.all([
    openQueue().select("issue").distinct().orderBy("issue").execute(),
    openQueue().select("make_name").distinct().where("make_name", "is not", null).orderBy("make_name").execute(),
    openQueue().select("country").distinct().where("country", "<>", "").orderBy("country").execute(),
  ]);
  return {
    issues: issues.map((r) => r.issue).filter((v): v is string => !!v),
    makes: makes.map((r) => r.make_name).filter((v): v is string => !!v),
    countries: countries.map((r) => r.country).filter((v): v is string => !!v),
  };
}

/** The next case to review (in queue order, with the same filters), skipping ``excludeId`` and
 *  cases that already have a decision waiting. */
export async function nextCaseId(filters: QueueFilters, excludeId: string): Promise<string | null> {
  await io();
  const row = await reviewOrder(
    applyFilters(openQueue() as QueueQuery, { ...filters, page: undefined })
      .where("queued_decision_id", "is", null)
      .where("id", "<>", excludeId),
  )
    .select("id")
    .limit(1)
    .executeTakeFirst();
  return row?.id ?? null;
}
