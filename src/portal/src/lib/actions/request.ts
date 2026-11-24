"use server";

import { refresh } from "next/cache";
import type { z } from "zod";

import { userWithRole } from "@/lib/auth/current-user";
import { ACTION_ROLE, ROLE_LABEL, type ActionKind } from "@/lib/auth/roles";
import { getDb } from "@/lib/db";

import {
  catalogUpsertSchema,
  decideCaseSchema,
  evolutionNoteSchema,
  mergeGenerationsSchema,
  setValueSchema,
  splitGenerationSchema,
  userUpsertSchema,
} from "./schemas";

export type RequestState =
  { status: "idle" } | { status: "queued"; actionId: string } | { status: "error"; error: string };

/**
 * Queues a request for the worker. Server actions are reachable by direct POST, so the role
 * is checked here too (the worker checks it again; it is the real guard). The requester is
 * always the verified identity, never a form field.
 */
async function queue(kind: ActionKind, payload: Record<string, unknown>): Promise<RequestState> {
  const user = await userWithRole(ACTION_ROLE[kind]);
  if (!user) return { status: "error", error: `Necesitas el rol ${ROLE_LABEL[ACTION_ROLE[kind]].toLowerCase()}.` };
  const row = await getDb()
    .insertInto("kb.web_action")
    .values({ kind, payload: JSON.stringify(payload), requested_by: user.email })
    .returning("id")
    .executeTakeFirstOrThrow();
  refresh();
  return { status: "queued", actionId: String(row.id) };
}

/** Form fields as plain strings (a checkbox that isn't ticked is absent). */
function fields(form: FormData): Record<string, string | undefined> {
  const out: Record<string, string | undefined> = {};
  for (const [k, v] of form.entries()) if (typeof v === "string" && !k.startsWith("$")) out[k] = v;
  return out;
}

async function parseAndQueue<S extends z.ZodType>(kind: ActionKind, schema: S, form: FormData): Promise<RequestState> {
  const parsed = schema.safeParse(fields(form));
  if (!parsed.success) return { status: "error", error: parsed.error.issues[0]?.message ?? "Datos inválidos." };
  return queue(kind, parsed.data as Record<string, unknown>);
}

export async function decideCase(_prev: RequestState, form: FormData): Promise<RequestState> {
  return parseAndQueue("decide_case", decideCaseSchema, form);
}

export async function setValue(_prev: RequestState, form: FormData): Promise<RequestState> {
  return parseAndQueue("set_value", setValueSchema, form);
}

export async function splitGeneration(_prev: RequestState, form: FormData): Promise<RequestState> {
  return parseAndQueue("split_generation", splitGenerationSchema, form);
}

export async function mergeGenerations(_prev: RequestState, form: FormData): Promise<RequestState> {
  return parseAndQueue("merge_generations", mergeGenerationsSchema, form);
}

export async function addEvolutionNote(_prev: RequestState, form: FormData): Promise<RequestState> {
  return parseAndQueue("add_evolution_note", evolutionNoteSchema, form);
}

export async function upsertCatalog(_prev: RequestState, form: FormData): Promise<RequestState> {
  return parseAndQueue("catalog_upsert", catalogUpsertSchema, form);
}

export async function upsertUser(_prev: RequestState, form: FormData): Promise<RequestState> {
  return parseAndQueue("user_upsert", userUpsertSchema, form);
}

export async function recalculate(_prev: RequestState, _form: FormData): Promise<RequestState> {
  void _form;
  return queue("recalculate", {});
}
