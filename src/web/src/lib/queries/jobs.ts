import "server-only";

import { sql } from "kysely";
import { io } from "next/cache";

import { getDb } from "@/lib/db";
import { ESTIMATE_MAX_AGE_MIN, type EstimateResult } from "@/lib/jobs";

const ID = /^\d{1,18}$/;

const JOB_COLUMNS = [
  "j.id",
  "j.command",
  "j.params",
  "j.requested_by",
  "j.status",
  "j.summary",
  "j.result",
  "j.error",
  "j.created_at",
  "j.started_at",
  "j.finished_at",
  "f.filename",
  "f.size",
] as const;

export async function listJobs(limit = 50) {
  await io();
  return getDb()
    .selectFrom("kb.job as j")
    .leftJoin("kb.job_file as f", "f.job_id", "j.id")
    .select(JOB_COLUMNS)
    .orderBy("j.id", "desc")
    .limit(limit)
    .execute();
}

export type JobRow = Awaited<ReturnType<typeof listJobs>>[number];

export async function getJob(id: string) {
  await io();
  if (!ID.test(id)) return null;
  const job = await getDb()
    .selectFrom("kb.job as j")
    .leftJoin("kb.job_file as f", "f.job_id", "j.id")
    .select(JOB_COLUMNS)
    .select(
      sql<boolean>`j.status = 'done' and j.finished_at > now() - make_interval(mins => ${ESTIMATE_MAX_AGE_MIN})`.as(
        "fresh",
      ),
    )
    .where("j.id", "=", id)
    .executeTakeFirst();
  return job ?? null;
}

/** An estimate that can still be sent: finished, recent, with something to send. */
export async function sendableEstimate(id: string): Promise<EstimateResult | null> {
  const job = await getJob(id);
  if (!job || job.command !== "ai_estimate" || !job.fresh) return null;
  const r = job.result as EstimateResult | null;
  return r && r.requests > 0 && r.estimate ? r : null;
}

/** What the AI runs submitted since ``start`` cost: the real cost once collected, the estimate
 *  until then (the same sum as kb/budget.py spent_since). */
export async function aiSpentSince(start: string): Promise<number> {
  await io();
  const since = new Date(start);
  if (Number.isNaN(since.getTime())) return Number.POSITIVE_INFINITY; // unreadable: block, never guess
  const row = await getDb()
    .selectFrom("kb.ai_run")
    .select(sql<string>`coalesce(sum(coalesce(actual_cost_usd, est_cost_usd)), 0)`.as("usd"))
    .where("submitted_at", ">=", since)
    .executeTakeFirstOrThrow();
  return Number(row.usd);
}

/** AI runs still waiting to be collected. */
export async function submittedRuns() {
  await io();
  return getDb()
    .selectFrom("kb.ai_run")
    .select(["id", "kind", "request_count", "submitted_at", "est_cost_usd"])
    .where("status", "=", "submitted")
    .orderBy("id", "desc")
    .execute();
}

export async function jobFile(id: string) {
  if (!ID.test(id)) return null;
  return (
    (await getDb()
      .selectFrom("kb.job_file")
      .select(["filename", "content_type", "gzipped", "bytes"])
      .where("job_id", "=", id)
      .executeTakeFirst()) ?? null
  );
}
