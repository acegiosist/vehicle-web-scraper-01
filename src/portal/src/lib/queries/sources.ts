import "server-only";

import { sql } from "kysely";
import { io } from "next/cache";

import { getDb } from "@/lib/db";

/** kb.external_source (migration 0017), lowest priority number first. */
export async function externalSources() {
  await io();
  return getDb().selectFrom("kb.external_source").selectAll().orderBy("priority").orderBy("code").execute();
}
export type ExternalSource = Awaited<ReturnType<typeof externalSources>>[number];

/** The sources the generation page offers: active, not paid, and for one of its countries (none = all). */
export function applicableSources(sources: ExternalSource[], countries: string[]) {
  return sources.filter(
    (s) => s.active && !s.paid && (s.countries.length === 0 || s.countries.some((c) => countries.includes(c))),
  );
}

export interface LookupProposal {
  entity_type: "generation" | "powertrain";
  entity_id: number;
  field: string;
  value: unknown;
  records: number;
  alternatives: Record<string, number>;
  years: number[];
  matched: string[];
  current: { value: unknown; source_kind: string | null; source_code: string | null };
}

export interface LookupResult {
  source: string;
  source_name: string;
  credit: string;
  generation_id: number;
  years: number[];
  powertrains: number[];
  notes: string[];
  proposals: LookupProposal[];
}

/**
 * The generation's latest lookups (source_lookup) with their proposals, and which of them
 * already have a source_apply. Read them before the generation's data, like recentActionsFor.
 */
export async function lookupsFor(generationId: number, limit = 5) {
  await io();
  const db = getDb();
  const match = JSON.stringify({ generation_id: generationId });
  const [lookups, applies] = await Promise.all([
    db.selectFrom("kb.web_action")
      .select(["id", "status", "error", "requested_by", "requested_at", "result",
               sql<string>`payload->>'source'`.as("source")])
      .where("kind", "=", "source_lookup")
      .where(sql<boolean>`payload @> ${match}::jsonb`)
      .orderBy("id", "desc")
      .limit(limit)
      .execute(),
    db.selectFrom("kb.web_action")
      .select(["id", "status", sql<string>`payload->>'lookup_id'`.as("lookup_id")])
      .where("kind", "=", "source_apply")
      .where(sql<boolean>`payload @> ${match}::jsonb`)
      .where("status", "!=", "failed")
      .execute(),
  ]);
  const saved = new Map(applies.map((a) => [a.lookup_id, a]));
  return lookups.map((l) => ({
    ...l,
    result: l.result as unknown as LookupResult | null,
    saved: saved.get(String(l.id)) ?? null,
  }));
}
export type Lookup = Awaited<ReturnType<typeof lookupsFor>>[number];
