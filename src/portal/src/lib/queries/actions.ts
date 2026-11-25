import "server-only";

import { sql } from "kysely";
import { io } from "next/cache";

import { getDb } from "@/lib/db";

export const ACTIONS_PAGE_SIZE = 50;

const COLUMNS = ["id", "kind", "status", "error", "requested_by", "requested_at", "applied_at"] as const;
// An uploaded capture template travels in the payload (and a prepared one in the result) as
// base64: lists never read it, only the download route does.
const payload = sql<Record<string, unknown> | null>`payload - 'file_b64'`.as("payload");
const result = sql<Record<string, unknown> | null>`result - 'file_b64'`.as("result");

/**
 * Requests whose payload contains any of these objects (jsonb @>), newest first.
 *
 * Read them BEFORE the data they change, not in parallel: the worker commits a change and marks
 * its request applied in one transaction, so a request read as applied guarantees the data read
 * afterwards includes it, and one read as queued keeps the page refreshing (RefreshWhile).
 * The other order can show "Aplicada" next to the old value, and the page then stops refreshing.
 */
export async function recentActionsFor(matches: Record<string, unknown>[], limit = 10) {
  await io();
  if (!matches.length) return [];
  return getDb()
    .selectFrom("kb.web_action")
    .select([...COLUMNS, payload])
    .where((eb) => eb.or(matches.map((m) => sql<boolean>`payload @> ${JSON.stringify(m)}::jsonb`)))
    .orderBy("id", "desc")
    .limit(limit)
    .execute();
}
export type RecentAction = Awaited<ReturnType<typeof recentActionsFor>>[number];

export async function actionsPage(status: string | undefined, page: number) {
  await io();
  let q = getDb().selectFrom("kb.web_action");
  if (status) q = q.where("status", "=", status);
  const [rows, total] = await Promise.all([
    q.select([...COLUMNS, payload, result]).orderBy("id", "desc").limit(ACTIONS_PAGE_SIZE)
      .offset((page - 1) * ACTIONS_PAGE_SIZE).execute(),
    q.select((eb) => eb.fn.countAll<string>().as("n")).executeTakeFirstOrThrow(),
  ]);
  return { rows, total: Number(total.n) };
}

/** The capture page's requests (prepare a template, upload one), newest first, without files. */
export async function captureActions(limit = 10) {
  await io();
  return getDb()
    .selectFrom("kb.web_action")
    .select([...COLUMNS, payload, result])
    .where("kind", "in", ["export_specs", "import_specs"])
    .orderBy("id", "desc")
    .limit(limit)
    .execute();
}
export type CaptureAction = Awaited<ReturnType<typeof captureActions>>[number];

/** A prepared template's file, or undefined (not applied, or not a template). */
export async function templateFile(id: string) {
  if (!/^\d+$/.test(id)) return undefined;
  const row = await getDb()
    .selectFrom("kb.web_action")
    .select([sql<string | null>`result->>'file_name'`.as("name"), sql<string | null>`result->>'file_b64'`.as("data")])
    .where("id", "=", id)
    .where("kind", "=", "export_specs")
    .where("status", "=", "applied")
    .executeTakeFirst();
  return row?.data ? { name: row.name ?? "plantilla-captura.xlsx", data: Buffer.from(row.data, "base64") } : undefined;
}

/** Every catalog with its values, for the Catálogos page. */
export async function catalogTables() {
  await io();
  const db = getDb();
  const tables = ["segment", "headlight_type", "brake_type", "body_style", "fuel_type", "transmission_type",
                  "drivetrain", "exclusion_reason", "vehicle_class", "country"] as const;
  const rows = await Promise.all(
    tables.map((t) => db.selectFrom(`kb.${t}` as "kb.fuel_type").selectAll().orderBy("code").execute()),
  );
  return tables.map((t, i) => ({ table: t, rows: rows[i] as Record<string, unknown>[] }));
}

export async function users() {
  await io();
  return getDb().selectFrom("kb.app_user").selectAll().orderBy("active", "desc").orderBy("email").execute();
}
