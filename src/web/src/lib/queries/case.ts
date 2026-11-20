import "server-only";

import { sql } from "kysely";
import { io } from "next/cache";

import { getDb } from "@/lib/db";
import { FIELDS, isField } from "@/lib/fields";

const ID = /^\d{1,18}$/;

export async function getCase(id: string) {
  await io();
  if (!ID.test(id)) return null;
  const db = getDb();
  const item = await db.selectFrom("kb.review_queue").selectAll().where("id", "=", id).executeTakeFirst();
  if (!item) return null;
  const decisions = await db
    .selectFrom("kb.review_decision")
    .select([
      "id",
      "decision",
      "corrected_value",
      "note",
      "reviewer",
      "status",
      "error",
      "submitted_at",
      "processed_at",
    ])
    .where("review_item_id", "=", id)
    .orderBy("id", "desc")
    .limit(20)
    .execute();
  return { item, decisions };
}

export type ReviewCase = NonNullable<Awaited<ReturnType<typeof getCase>>>;
export type CaseDecision = ReviewCase["decisions"][number];

/** The field a case is about: its own, or the displacement for the variant cross-checks. */
export function caseField(item: ReviewCase["item"]): string | null {
  if (isField(item.field)) return item.field;
  if (item.entity_type === "variant") return "engine_displacement_l";
  return null;
}

/** Listings behind a case (current version from staging), with the value of the case's field. */
export async function caseListings(item: ReviewCase["item"], limit = 25) {
  await io();
  const db = getDb();
  const field = caseField(item);
  let q = db
    .selectFrom("kb.listing as l")
    .innerJoin("staging.raw_listing as r", (j) =>
      j
        .onRef("r.source_site", "=", "l.source_site")
        .onRef("r.listing_id", "=", "l.listing_id")
        .on("r.valid_to", "is", null),
    );
  const id = item.entity_id;
  if (!id) return { rows: [], total: 0, field };
  switch (item.entity_type) {
    case "make":
      q = q.where("l.make_id", "=", id);
      break;
    case "model":
      q = q.where("l.model_id", "=", id);
      break;
    case "trim":
      q = q.where("l.trim_id", "=", id);
      break;
    case "variant":
    case "spec":
      q = q.where("l.variant_id", "=", id);
      break;
    case "listing":
      q = q.where(sql<string>`kb.listing_number(l.source_site, l.listing_id)`, "=", id);
      break;
    default:
      return { rows: [], total: 0, field };
  }
  if (item.country && item.entity_type === "spec" && FIELDS[item.field ?? ""]?.group === "equip") {
    q = q.where("l.country", "=", item.country);
  }
  const valueExpr = field ? sql<unknown>`r.row -> ${field}` : sql<unknown>`null`;
  const [rows, total] = await Promise.all([
    q
      .select([
        "l.source_site",
        "l.listing_id",
        "l.country",
        "l.raw_make",
        "l.raw_model",
        "l.raw_trim",
        "l.raw_year",
        "l.excluded_reason",
        sql<string | null>`r.row ->> 'source_url'`.as("url"),
        sql<number | null>`(r.row ->> 'price')::float8`.as("price"),
        sql<string | null>`r.row ->> 'currency'`.as("currency"),
        sql<number | null>`(r.row ->> 'mileage_km')::int`.as("mileage_km"),
        valueExpr.as("value"),
      ])
      .orderBy("l.listed_at", (ob) => ob.desc().nullsLast())
      .orderBy("l.listing_id")
      .limit(limit)
      .execute(),
    q.select((eb) => eb.fn.countAll<string>().as("n")).executeTakeFirstOrThrow(),
  ]);
  return { rows, total: Number(total.n), field };
}

/** How the listings of a variant split on the case's field (spec cases). */
export async function valueDistribution(item: ReviewCase["item"]) {
  await io();
  const field = caseField(item);
  if (!field || !item.entity_id || !["spec", "variant"].includes(item.entity_type ?? "")) return [];
  const rows = await getDb()
    .selectFrom("kb.listing as l")
    .innerJoin("staging.raw_listing as r", (j) =>
      j
        .onRef("r.source_site", "=", "l.source_site")
        .onRef("r.listing_id", "=", "l.listing_id")
        .on("r.valid_to", "is", null),
    )
    .select((eb) => [sql<string | null>`r.row ->> ${field}`.as("value"), eb.fn.countAll<string>().as("n")])
    .where("l.variant_id", "=", item.entity_id)
    .groupBy(sql`1`) // the value column: a bound parameter can't be repeated in GROUP BY
    .orderBy(sql`count(*)`, "desc")
    .limit(10)
    .execute();
  return rows.map((r) => ({ value: r.value, n: Number(r.n) }));
}

/** The value currently published for a spec case (variant_spec / variant_market_spec). */
export async function publishedValue(item: ReviewCase["item"]): Promise<unknown> {
  await io();
  const field = item.field;
  if (item.entity_type !== "spec" || !isField(field) || !item.entity_id) return undefined;
  const spec = FIELDS[field];
  const column = sql.ref(field); // whitelisted by isField(): only catalog names reach SQL
  const db = getDb();
  if (spec.group === "equip") {
    const row = await db
      .selectFrom("kb.variant_market_spec")
      .select(column.as("value"))
      .where("variant_id", "=", item.entity_id)
      .where("country", "=", item.country ?? "")
      .executeTakeFirst();
    return row?.value;
  }
  if (spec.group === "key") {
    const row = await db
      .selectFrom("kb.variant")
      .select(column.as("value"))
      .where("id", "=", item.entity_id)
      .executeTakeFirst();
    return row?.value;
  }
  const row = await db
    .selectFrom("kb.variant_spec")
    .select(column.as("value"))
    .where("variant_id", "=", item.entity_id)
    .executeTakeFirst();
  return row?.value;
}

/** Existing names a correction can point to: accepted makes, or accepted models of the make. */
export async function correctionTargets(item: ReviewCase["item"]): Promise<string[]> {
  await io();
  const db = getDb();
  if (item.entity_type === "make") {
    const rows = await db
      .selectFrom("kb.make")
      .select("name")
      .where("status", "=", "accepted")
      .where("id", "<>", item.entity_id ?? "0")
      .orderBy("name")
      .limit(500)
      .execute();
    return rows.map((r) => r.name);
  }
  if (item.entity_type === "model" && item.make_id) {
    const rows = await db
      .selectFrom("kb.model")
      .select("name")
      .where("make_id", "=", item.make_id)
      .where("status", "=", "accepted")
      .where("id", "<>", item.entity_id ?? "0")
      .orderBy("name")
      .limit(500)
      .execute();
    return rows.map((r) => r.name);
  }
  return [];
}
