import "server-only";

import { io } from "next/cache";

import { getDb } from "@/lib/db";
import { type DecisionFilters, PAGE_SIZE } from "@/lib/filters";

export async function listDecisions(filters: DecisionFilters) {
  await io();
  const page = filters.page ?? 1;
  let base = getDb().selectFrom("kb.review_decision as d").leftJoin("kb.review_queue as q", "q.id", "d.review_item_id");
  if (filters.reviewer) base = base.where("d.reviewer", "=", filters.reviewer);
  if (filters.status) base = base.where("d.status", "=", filters.status);
  const [rows, total, reviewers] = await Promise.all([
    base
      .select([
        "d.id",
        "d.review_item_id",
        "d.decision",
        "d.corrected_value",
        "d.note",
        "d.reviewer",
        "d.status",
        "d.error",
        "d.submitted_at",
        "d.processed_at",
        "q.issue",
        "q.field",
        "q.entity_label",
        "q.level",
      ])
      .orderBy("d.id", "desc")
      .limit(PAGE_SIZE)
      .offset((page - 1) * PAGE_SIZE)
      .execute(),
    base.select((eb) => eb.fn.countAll<string>().as("n")).executeTakeFirstOrThrow(),
    getDb().selectFrom("kb.review_decision").select("reviewer").distinct().orderBy("reviewer").execute(),
  ]);
  return {
    rows,
    total: Number(total.n),
    page,
    pageCount: Math.max(1, Math.ceil(Number(total.n) / PAGE_SIZE)),
    reviewers: reviewers.map((r) => r.reviewer),
  };
}
