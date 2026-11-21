// Jobs the site can queue in kb.job (migration 0003). The Python worker runs them with
// src/vehicle_scraper/kb/commands.py and validates the parameters again (worker.execute_job).
// Pure module: used by the Server Actions, the pages and the unit tests.
import { z } from "zod";

export const JOB_COMMANDS = [
  "normalize",
  "consolidate",
  "recalculate",
  "export",
  "ai_estimate",
  "ai_collect",
  "ai_submit",
] as const;
export type JobCommand = (typeof JOB_COMMANDS)[number];
export type JobStatus = "queued" | "running" | "done" | "failed" | "canceled";

export const COMMAND_LABELS: Record<JobCommand, string> = {
  normalize: "Normalizar identidad",
  consolidate: "Consolidar fichas",
  recalculate: "Recalcular (normalizar + consolidar)",
  export: "Exportar anuncios",
  ai_estimate: "IA: estimar costo",
  ai_collect: "IA: recoger resultados",
  ai_submit: "IA: enviar a Claude",
};

export const JOB_STATUS: Record<
  JobStatus,
  { label: string; variant: "default" | "secondary" | "destructive" | "outline" }
> = {
  queued: { label: "En cola", variant: "secondary" },
  running: { label: "Corriendo", variant: "secondary" },
  done: { label: "Terminada", variant: "default" },
  failed: { label: "Falló", variant: "destructive" },
  canceled: { label: "Cancelada", variant: "outline" },
};

/** How long an estimate can be used to send (must match ESTIMATE_MAX_AGE_MIN in worker.py). */
export const ESTIMATE_MAX_AGE_MIN = 60;

const text = (fd: FormData, key: string) => {
  const v = fd.get(key);
  return typeof v === "string" ? v.trim() : "";
};
const optionalInt = (min: number, max: number) =>
  z.preprocess(
    (v) => (v === "" || v === undefined ? undefined : Number(v)),
    z.number().int().min(min).max(max).optional(),
  );

const exportSchema = z.object({
  format: z.enum(["csv", "xlsx", "json"], { error: "Formato inválido." }),
  with_sources: z.boolean(),
});

const estimateSchema = z.object({
  kind: z.enum(["identity", "specs"], { error: "Elige identidad o fichas." }),
  effort: z.enum(["low", "medium", "high"]).optional(),
  makes: z
    .array(z.string().min(1).max(60, "Cada marca admite máximo 60 caracteres."))
    .max(50, "Máximo 50 marcas.")
    .optional(),
  limit: optionalInt(1, 10_000),
  min_listings: optionalInt(1, 1000),
  count_tokens: z.boolean().optional(),
});

const collectSchema = z.object({ run_id: optionalInt(1, Number.MAX_SAFE_INTEGER) });

export type JobRequest = { command: JobCommand; params: Record<string, unknown> };
export type ParsedJob = { ok: true; job: JobRequest } | { ok: false; error: string };

/** Drops undefined values so equal requests give equal JSON (the "same job twice" index). */
function clean(o: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined));
}

/** A job from one of the forms on /tareas. ai_submit is not here: it needs its own checks. */
export function parseJobForm(fd: FormData): ParsedJob {
  const command = text(fd, "command");
  const fail = (e: z.ZodError): ParsedJob => ({ ok: false, error: e.issues[0]?.message ?? "Datos inválidos." });
  switch (command) {
    case "normalize":
    case "consolidate":
    case "recalculate":
      return { ok: true, job: { command, params: {} } };
    case "export": {
      const r = exportSchema.safeParse({ format: text(fd, "format"), with_sources: fd.get("with_sources") === "on" });
      return r.success ? { ok: true, job: { command, params: clean(r.data) } } : fail(r.error);
    }
    case "ai_estimate": {
      const makes = text(fd, "makes")
        .split(",")
        .map((m) => m.trim())
        .filter(Boolean);
      const kind = text(fd, "kind");
      const r = estimateSchema.safeParse({
        kind,
        effort: text(fd, "effort") || undefined,
        makes: makes.length ? [...new Set(makes)].sort() : undefined,
        limit: text(fd, "limit"),
        min_listings: kind === "specs" ? text(fd, "min_listings") : undefined,
        count_tokens: fd.get("count_tokens") === "on" ? true : undefined,
      });
      return r.success ? { ok: true, job: { command, params: clean(r.data) } } : fail(r.error);
    }
    case "ai_collect": {
      const r = collectSchema.safeParse({ run_id: text(fd, "run_id") });
      return r.success ? { ok: true, job: { command, params: clean(r.data) } } : fail(r.error);
    }
    default:
      return { ok: false, error: "Comando no permitido desde el sitio." };
  }
}

/** The reviewer must type the estimated amount exactly (e.g. "33.36" or "33,36"). */
export function confirmsAmount(typed: string, costUsd: number): boolean {
  const t = typed
    .trim()
    .replace(/^US\$|^\$/i, "")
    .replace(",", ".");
  if (!/^\d+(\.\d{1,2})?$/.test(t)) return false;
  return Math.round(Number(t) * 100) === Math.round(costUsd * 100);
}

/** A download name safe for a Content-Disposition header. */
export function safeFilename(name: string): string {
  const base = name.replace(/[^A-Za-z0-9._-]/g, "_").replace(/^\.+/, "");
  return base.slice(0, 100) || "descarga";
}

export interface EstimateResult {
  requests: number;
  skipped: number;
  model?: string;
  fingerprint: string;
  params: {
    kind: "identity" | "specs";
    effort: string;
    makes: string[] | null;
    limit: number | null;
    min_listings: number | null;
  };
  estimate?: {
    requests: number;
    input_tokens: number;
    output_tokens_est: number;
    method: string;
    cost_usd_est: number;
    cost_usd_range: [number, number];
  };
  /** Missing on estimates made before the spending limit existed. */
  budget?: AiBudget;
}

/** The AI spending limit as the worker saw it when estimating (kb/budget.py, Budget.as_json):
 *  KB_AI_BUDGET_USD per KB_AI_BUDGET_PERIOD, from the repository's .env. */
export interface AiBudget {
  limit_usd: number | null;
  period: AiBudgetPeriod;
  /** ISO dates in the worker's local time */
  period_start: string;
  resets_at: string;
  spent_usd: number;
  remaining_usd: number | null;
  allows: boolean;
  error: string | null;
  message: string | null;
}

export type AiBudgetPeriod = "daily" | "weekly" | "monthly";

export const BUDGET_PERIOD_LABELS: Record<AiBudgetPeriod, string> = {
  daily: "hoy",
  weekly: "esta semana",
  monthly: "este mes",
};

/** "22/11 00:00" from an ISO date with offset, read as written (the worker's local time). */
export function formatResetsAt(iso: string): string {
  const m = /^\d{4}-(\d{2})-(\d{2})T(\d{2}:\d{2})/.exec(iso);
  return m ? `${m[2]}/${m[1]} ${m[3]}` : iso;
}

/** Whether sending ``cost`` fits the budget, with what was spent in the period read *now* (another
 *  batch may have been sent after the estimate). Mirrors Budget.refusal in kb/budget.py; the
 *  worker checks again before sending, this only decides what the page offers. */
export function budgetVerdict(
  budget: AiBudget | undefined,
  spentNow: number,
  cost: number,
): { allowed: boolean; message: string | null } {
  if (!budget) {
    return {
      allowed: false,
      message: "Este estimado no trae el límite de gasto en IA (es anterior al límite): estima de nuevo.",
    };
  }
  if (budget.error || budget.limit_usd === null) {
    return { allowed: false, message: `No se puede enviar a Claude: ${budget.error ?? "falta el límite de gasto."}` };
  }
  if (spentNow + cost > budget.limit_usd + 1e-9) {
    return {
      allowed: false,
      message:
        `Se superó el límite de gasto en IA: llevas US$${spentNow.toFixed(2)} de US$${budget.limit_usd.toFixed(2)} ` +
        `${BUDGET_PERIOD_LABELS[budget.period] ?? budget.period} y este envío costaría US$${cost.toFixed(2)}. ` +
        `Se reinicia el ${formatResetsAt(budget.resets_at)}.`,
    };
  }
  return { allowed: true, message: null };
}

/** A short readable description of a job's parameters. */
export function describeParams(command: string, params: unknown): string {
  const p = (params && typeof params === "object" ? params : {}) as Record<string, unknown>;
  if (command === "export") return `${String(p.format ?? "csv").toUpperCase()}${p.with_sources ? ", con origen" : ""}`;
  if (command === "ai_estimate") {
    const parts = [p.kind === "specs" ? "fichas" : "identidad"];
    if (p.effort) parts.push(`esfuerzo ${p.effort}`);
    if (Array.isArray(p.makes)) parts.push(`marcas: ${p.makes.join(", ")}`);
    if (p.limit) parts.push(`máx. ${p.limit} requests`);
    if (p.min_listings) parts.push(`≥ ${p.min_listings} anuncios`);
    if (p.count_tokens) parts.push("tokens exactos");
    return parts.join(" · ");
  }
  if (command === "ai_collect") return p.run_id ? `corrida ${p.run_id}` : "última corrida enviada";
  if (command === "ai_submit") return `estimado #${p.estimate_job_id} · hasta US$${p.confirm_usd}`;
  return "";
}
