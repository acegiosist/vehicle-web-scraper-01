"use server";

import { refresh } from "next/cache";
import type { z } from "zod";

import { userWithRole } from "@/lib/auth/current-user";
import { ACTION_ROLE, ROLE_LABEL, type ActionKind } from "@/lib/auth/roles";
import { getDb } from "@/lib/db";

import {
  catalogUpsertSchema,
  checkSpecsFile,
  decideCaseSchema,
  evolutionNoteSchema,
  exportSpecsSchema,
  mergeGenerationsSchema,
  parseAccepted,
  setValueSchema,
  sourceLookupSchema,
  sourceUpdateSchema,
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

export async function exportSpecs(_prev: RequestState, form: FormData): Promise<RequestState> {
  return parseAndQueue("export_specs", exportSpecsSchema, form);
}

/** A filled capture template: the file travels to the worker inside the request (base64). */
export async function importSpecs(_prev: RequestState, form: FormData): Promise<RequestState> {
  const file = form.get("file");
  const error = checkSpecsFile(file instanceof File ? file : null);
  if (error) return { status: "error", error };
  const f = file as File;
  const data = Buffer.from(await f.arrayBuffer());
  if (data.subarray(0, 2).toString("latin1") !== "PK") return { status: "error", error: "No es un archivo .xlsx válido." };
  return queue("import_specs", { file_name: f.name.slice(0, 120), file_b64: data.toString("base64") });
}

/** Ask a source about one generation; the worker answers in the action's result (nothing is saved). */
export async function lookupSource(_prev: RequestState, form: FormData): Promise<RequestState> {
  return parseAndQueue("source_lookup", sourceLookupSchema, form);
}

/** Save the values ticked in the comparison; the worker takes them from the lookup, not from here. */
export async function applySource(_prev: RequestState, form: FormData): Promise<RequestState> {
  const lookupId = Number(form.get("lookup_id"));
  if (!Number.isInteger(lookupId) || lookupId <= 0) return { status: "error", error: "Consulta inválida." };
  const accept = parseAccepted(form.getAll("accept"));
  if (typeof accept === "string") return { status: "error", error: accept };
  const generationId = Number(form.get("generation_id"));
  // generation_id only lets the generation page find this request; the worker uses the lookup's
  return queue("source_apply", {
    lookup_id: lookupId,
    ...(Number.isInteger(generationId) && generationId > 0 ? { generation_id: generationId } : {}),
    accept,
  });
}

export async function updateSource(_prev: RequestState, form: FormData): Promise<RequestState> {
  return parseAndQueue("source_update", sourceUpdateSchema, form);
}

export async function recalculate(_prev: RequestState, _form: FormData): Promise<RequestState> {
  void _form;
  return queue("recalculate", {});
}
