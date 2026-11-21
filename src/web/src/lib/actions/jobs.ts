"use server";

import { refresh } from "next/cache";
import { redirect } from "next/navigation";
import { DatabaseError } from "pg";
import { sql } from "kysely";

import { getDb } from "@/lib/db";
import { aiSubmitEnabled } from "@/lib/flags";
import { budgetVerdict, confirmsAmount, type JobRequest, parseJobForm } from "@/lib/jobs";
import { aiSpentSince, sendableEstimate } from "@/lib/queries/jobs";
import { getReviewer } from "@/lib/reviewer";

export type JobFormState = { error?: string };

async function insertJob(job: JobRequest, reviewer: string): Promise<{ id: string } | { error: string }> {
  try {
    const row = await getDb()
      .insertInto("kb.job")
      .values({ command: job.command, params: JSON.stringify(job.params), requested_by: reviewer })
      .returning("id")
      .executeTakeFirstOrThrow();
    return { id: row.id };
  } catch (err) {
    if (err instanceof DatabaseError && err.code === "23505") {
      return { error: "Ya hay una tarea igual en cola o corriendo." };
    }
    console.error("insertJob failed", err);
    return { error: "No se pudo encolar la tarea. Intenta de nuevo." };
  }
}

/** Queues one of the /tareas forms. Reachable by direct POST: everything is validated here. */
export async function enqueueJob(_prev: JobFormState, formData: FormData): Promise<JobFormState> {
  const reviewer = await getReviewer();
  if (!reviewer) return { error: "Escribe tu nombre arriba a la derecha antes de lanzar una tarea." };
  const parsed = parseJobForm(formData);
  if (!parsed.ok) return { error: parsed.error };
  const res = await insertJob(parsed.job, reviewer);
  if ("error" in res) return res;
  redirect(`/tareas/${res.id}`);
}

/** Cancels a job that has not started (kb.cancel_job: the only update the site's role may do). */
export async function cancelJob(formData: FormData): Promise<void> {
  const id = formData.get("jobId");
  if (!(await getReviewer()) || typeof id !== "string" || !/^\d{1,18}$/.test(id)) return;
  await sql`select kb.cancel_job(${id}::bigint)`.execute(getDb());
  refresh();
}

/** Queues ai_submit from an estimate, after the reviewer typed the estimated amount. */
export async function submitAiJob(_prev: JobFormState, formData: FormData): Promise<JobFormState> {
  if (!aiSubmitEnabled()) return { error: "Enviar a Claude desde el sitio está deshabilitado (KB_WEB_AI_SUBMIT)." };
  const reviewer = await getReviewer();
  if (!reviewer) return { error: "Escribe tu nombre arriba a la derecha antes de enviar." };
  const estimateId = formData.get("estimateJobId");
  const typed = formData.get("confirm");
  if (typeof estimateId !== "string" || typeof typed !== "string") return { error: "Datos inválidos." };
  const est = await sendableEstimate(estimateId);
  if (!est?.estimate) return { error: "El estimado ya no sirve (más de una hora o sin requests): estima de nuevo." };
  if (!confirmsAmount(typed, est.estimate.cost_usd_est)) {
    return { error: `Escribe exactamente el costo estimado: ${est.estimate.cost_usd_est.toFixed(2)}` };
  }
  // the spending limit with what was spent until now (the worker checks it again before sending)
  const spent = est.budget ? await aiSpentSince(est.budget.period_start) : 0;
  const verdict = budgetVerdict(est.budget, spent, est.estimate.cost_usd_est);
  if (!verdict.allowed) return { error: verdict.message ?? "Se superó el límite de gasto en IA." };
  const res = await insertJob(
    {
      command: "ai_submit",
      params: { estimate_job_id: Number(estimateId), confirm_usd: est.estimate.cost_usd_est },
    },
    reviewer,
  );
  if ("error" in res) return res;
  redirect(`/tareas/${res.id}`);
}
