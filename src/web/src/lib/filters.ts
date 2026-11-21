// Queue filters live in the URL (shareable, back button works). Everything from the URL is
// untrusted: unknown or malformed values are dropped, never passed to SQL.
import { z } from "zod";

import { ISSUES } from "./issues";

export const PAGE_SIZE = 50;

const one = (v: unknown) => (Array.isArray(v) ? v[0] : v);
const optional = <T extends z.ZodType>(schema: T) =>
  z.preprocess((v) => {
    const s = one(v);
    return typeof s === "string" && s.trim() !== "" ? s.trim() : undefined;
  }, schema.optional().catch(undefined));

export const queueFiltersSchema = z.object({
  level: optional(z.coerce.number().int().min(1).max(6)),
  issue: optional(z.string().refine((s) => Object.hasOwn(ISSUES, s))),
  entity: optional(z.enum(["make", "model", "trim", "listing", "variant", "spec"])),
  kind: optional(z.enum(["individual", "sample"])),
  /** ai: the proposal came from a Claude batch (review_queue.from_ai); rules: everything else */
  origin: optional(z.enum(["ai", "rules"])),
  make: optional(z.string().max(80)),
  country: optional(z.string().regex(/^[A-Z]{2}$/)),
  q: optional(z.string().max(100)),
  page: optional(z.coerce.number().int().min(1).max(10_000)),
});

export type QueueFilters = z.infer<typeof queueFiltersSchema>;

export function parseQueueFilters(params: Record<string, string | string[] | undefined>): QueueFilters {
  return queueFiltersSchema.parse(params);
}

/** Query string for the queue, with some filters replaced (``undefined`` removes one). */
export function queueHref(filters: QueueFilters, changes: Partial<QueueFilters> = {}): string {
  const merged = { ...filters, ...changes };
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(merged)) {
    if (v !== undefined && v !== null && v !== "" && !(k === "page" && v === 1)) qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `/cola?${s}` : "/cola";
}

/** A case page that remembers the queue filters (for "next case" and "back to the queue"). */
export function caseHref(id: string, filters: QueueFilters): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(filters)) if (v !== undefined && k !== "page") qs.set(k, String(v));
  const s = qs.toString();
  return `/cola/${id}${s ? `?${s}` : ""}`;
}

/** ILIKE pattern for free text, with the user's % and _ taken literally. */
export function likePattern(text: string): string {
  return `%${text.replace(/[\\%_]/g, (c) => `\\${c}`)}%`;
}

export const decisionFiltersSchema = z.object({
  reviewer: optional(z.string().max(60)),
  status: optional(z.enum(["queued", "applied", "failed", "superseded"])),
  page: optional(z.coerce.number().int().min(1).max(10_000)),
});

export type DecisionFilters = z.infer<typeof decisionFiltersSchema>;

export function parseDecisionFilters(params: Record<string, string | string[] | undefined>): DecisionFilters {
  return decisionFiltersSchema.parse(params);
}
