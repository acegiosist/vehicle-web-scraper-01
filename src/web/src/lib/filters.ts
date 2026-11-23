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

/** ``path`` plus the filters as a query string (no empty values, no ``page=1``). */
function withQuery(path: string, filters: Record<string, unknown>, dropPage = false): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(filters)) {
    if (v === undefined || v === null || v === "") continue;
    if (k === "page" && (dropPage || v === 1)) continue;
    qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `${path}?${s}` : path;
}

/** Query string for the queue, with some filters replaced (``undefined`` removes one). */
export function queueHref(filters: QueueFilters, changes: Partial<QueueFilters> = {}): string {
  return withQuery("/cola", { ...filters, ...changes });
}

/** A case page that remembers the queue filters (for "next case" and "back to the queue"). */
export function caseHref(id: string, filters: QueueFilters): string {
  return withQuery(`/cola/${id}`, filters, true);
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

/** Database ids (bigint) travel as digit strings. */
export const ID_PATTERN = /^\d{1,18}$/;

// Knowledge base browser (/base): make and model by id (names repeat across makes), model year.
export const knowledgeFiltersSchema = z.object({
  make: optional(z.string().regex(ID_PATTERN)),
  model: optional(z.string().regex(ID_PATTERN)),
  year: optional(z.coerce.number().int().min(1900).max(2100)),
  page: optional(z.coerce.number().int().min(1).max(10_000)),
});

export type KnowledgeFilters = z.infer<typeof knowledgeFiltersSchema>;

export function parseKnowledgeFilters(params: Record<string, string | string[] | undefined>): KnowledgeFilters {
  return knowledgeFiltersSchema.parse(params);
}

/** The knowledge base list, with some filters replaced (``undefined`` removes one). */
export function knowledgeHref(filters: KnowledgeFilters, changes: Partial<KnowledgeFilters> = {}): string {
  return withQuery("/base", { ...filters, ...changes });
}

/** A variant's sheet that remembers the list filters (for "back to the knowledge base"). */
export function variantHref(id: string, filters: KnowledgeFilters): string {
  return withQuery(`/base/${id}`, filters, true);
}
