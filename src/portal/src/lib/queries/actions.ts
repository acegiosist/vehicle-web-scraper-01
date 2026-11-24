import "server-only";

import { sql } from "kysely";
import { io } from "next/cache";

import { getDb } from "@/lib/db";

export const ACTIONS_PAGE_SIZE = 50;

const COLUMNS = ["id", "kind", "payload", "status", "error", "requested_by", "requested_at", "applied_at"] as const;

/** Requests whose payload contains any of these objects (jsonb @>), newest first. */
export async function recentActionsFor(matches: Record<string, unknown>[], limit = 10) {
  await io();
  if (!matches.length) return [];
  return getDb()
    .selectFrom("kb.web_action")
    .select([...COLUMNS])
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
    q.select([...COLUMNS, "result"]).orderBy("id", "desc").limit(ACTIONS_PAGE_SIZE)
      .offset((page - 1) * ACTIONS_PAGE_SIZE).execute(),
    q.select((eb) => eb.fn.countAll<string>().as("n")).executeTakeFirstOrThrow(),
  ]);
  return { rows, total: Number(total.n) };
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
