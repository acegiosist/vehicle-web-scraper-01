// AI runs (kb.ai_run) as the reviewers see them. The worker checks submitted batches every few
// minutes (kb worker --batch-check) and moves the finished ones to "ended"; collecting them is an
// ai_collect job. Pure module: usable on the server, in the browser and in tests.

export type RunStatus = "prepared" | "submitted" | "ended" | "applied" | "canceled";

export const RUN_STATUS: Record<RunStatus, string> = {
  prepared: "Preparada",
  submitted: "En proceso en Claude",
  ended: "Lista para recoger",
  applied: "Recogida",
  canceled: "Cancelada",
};

export function runStatusLabel(status: string | null | undefined): string {
  return (status && RUN_STATUS[status as RunStatus]) || (status ?? "—");
}

export function runKindLabel(kind: string | null | undefined): string {
  return kind === "identity" ? "identidad" : kind === "specs" ? "fichas" : (kind ?? "?");
}

/** Minutes between the worker's checks (kb worker --batch-check 300). */
export const BATCH_CHECK_MIN = 5;

export interface BatchCounts {
  succeeded: number;
  errored: number;
  expired: number;
  canceled: number;
  processing: number;
}

const COUNT_KEYS = ["succeeded", "errored", "expired", "canceled", "processing"] as const;

/** kb.ai_run.batch_counts (written by the worker) with anything malformed read as 0. */
export function parseCounts(json: unknown): BatchCounts | null {
  if (!json || typeof json !== "object" || Array.isArray(json)) return null;
  const src = json as Record<string, unknown>;
  const out = {} as BatchCounts;
  for (const k of COUNT_KEYS) {
    const v = src[k];
    out[k] = typeof v === "number" && Number.isInteger(v) && v >= 0 ? v : 0;
  }
  return out;
}

/** "5 de 5 correctas" or "3 de 5 correctas, 1 con error, 1 vencida". */
export function countsText(counts: BatchCounts | null, requests: number): string {
  if (!counts) return `${requests} ${requests === 1 ? "solicitud" : "solicitudes"}`;
  const total = Math.max(requests, counts.succeeded + counts.errored + counts.expired + counts.canceled);
  const parts = [`${counts.succeeded} de ${total} ${total === 1 ? "correcta" : "correctas"}`];
  if (counts.errored) parts.push(`${counts.errored} con error`);
  if (counts.expired) parts.push(`${counts.expired} ${counts.expired === 1 ? "vencida" : "vencidas"}`);
  if (counts.canceled) parts.push(`${counts.canceled} ${counts.canceled === 1 ? "cancelada" : "canceladas"}`);
  return parts.join(", ");
}

/** "hace 3 min", "hace 2 h", "hace 1 día": how long ago, coarse on purpose. */
export function sinceText(value: Date | string | null | undefined, now: number): string {
  if (!value) return "";
  const t = (value instanceof Date ? value : new Date(value)).getTime();
  if (Number.isNaN(t)) return "";
  const min = Math.max(0, Math.round((now - t) / 60_000));
  if (min < 1) return "hace menos de un minuto";
  if (min < 60) return `hace ${min} min`;
  const h = Math.round(min / 60);
  if (h < 24) return `hace ${h} h`;
  const d = Math.round(h / 24);
  return `hace ${d} ${d === 1 ? "día" : "días"}`;
}
