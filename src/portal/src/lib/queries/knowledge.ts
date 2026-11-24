import "server-only";

import { cache } from "react";
import { sql } from "kysely";
import { io } from "next/cache";

import { getDb } from "@/lib/db";
import { SOURCE_RANK, type Catalogs } from "@/lib/fields";

const CATALOG_TABLES = [
  "segment", "body_style", "fuel_type", "transmission_type", "drivetrain", "headlight_type", "brake_type",
  "country", "exclusion_reason",
] as const;

/** code -> Spanish name for every catalog, once per request. */
export const getCatalogs = cache(async (): Promise<Catalogs> => {
  await io();
  const db = getDb();
  const all = await Promise.all(
    CATALOG_TABLES.map((t) => db.selectFrom(`kb.${t}` as "kb.fuel_type").select(["code", "name_es"]).execute()),
  );
  return Object.fromEntries(CATALOG_TABLES.map((t, i) => [t, Object.fromEntries(all[i].map((r) => [r.code, r.name_es]))]));
});

export async function makes(q?: string) {
  await io();
  let query = getDb()
    .selectFrom("kb.make as k")
    .select([
      "k.id", "k.name", "k.status", "k.default_class",
      sql<string>`(select count(*) from kb.model m where m.make_id = k.id and m.status = 'accepted' and m.listings > 0)`.as("models"),
      sql<string>`(select count(*) from kb.generation g join kb.model m on m.id = g.model_id
                   where m.make_id = k.id and g.listings > 0)`.as("generations"),
      sql<string>`(select coalesce(sum(m.listings), 0) from kb.model m where m.make_id = k.id)`.as("listings"),
    ])
    .where("k.status", "!=", "rejected");
  if (q) query = query.where("k.name", "ilike", `%${q.replace(/[\\%_]/g, (m) => `\\${m}`)}%`);
  const rows = await query.orderBy("k.name").execute();
  return rows
    .map((r) => ({ ...r, models: Number(r.models), generations: Number(r.generations), listings: Number(r.listings) }))
    .filter((r) => r.listings > 0 || q);
}

export async function makeWithGenerations(id: string) {
  await io();
  if (!/^\d+$/.test(id)) return null;
  const db = getDb();
  const make = await db.selectFrom("kb.make").select(["id", "name", "status", "default_class"]).where("id", "=", id)
    .executeTakeFirst();
  if (!make) return null;
  const generations = await db
    .selectFrom("kb.model as m")
    .leftJoin("kb.generation as g", (j) => j.onRef("g.model_id", "=", "m.id").on("g.status", "!=", "rejected"))
    .select([
      "m.id as model_id", "m.name as model_name", "m.status as model_status", "m.listings as model_listings",
      "g.id as generation_id", "g.name as generation_name", "g.status as generation_status",
      "g.body_style_code", "g.year_from", "g.year_to", "g.observed_year_from", "g.observed_year_to",
      "g.listings as generation_listings", "g.segment_code",
    ])
    .where("m.make_id", "=", id)
    .where("m.listings", ">", 0)
    .orderBy("m.name")
    .orderBy("g.year_from")
    .orderBy("g.id")
    .execute();
  return { make, generations };
}

/** Published value + source of every field of one entity, from kb.spec_evidence. */
async function evidenceFor(entityType: "generation" | "powertrain" | "variant", id: string) {
  const rows = await getDb()
    .selectFrom("kb.spec_evidence")
    .select(["field", "source_kind", "value", "status", "support", "agreement"])
    .where("entity_type", "=", entityType)
    .where("entity_id", "=", id)
    .execute();
  const byField: Record<string, { published?: (typeof rows)[number]; candidates: typeof rows }> = {};
  for (const r of rows) {
    const e = (byField[r.field] ??= { candidates: [] });
    e.candidates.push(r);
    if (r.status === "accepted" && (!e.published || SOURCE_RANK[r.source_kind] < SOURCE_RANK[e.published.source_kind])) {
      e.published = r;
    }
  }
  return byField;
}
export type Evidence = Awaited<ReturnType<typeof evidenceFor>>;

export async function generation(id: string) {
  await io();
  if (!/^\d+$/.test(id)) return null;
  const db = getDb();
  const g = await db
    .selectFrom("kb.generation as g")
    .innerJoin("kb.model as m", "m.id", "g.model_id")
    .innerJoin("kb.make as k", "k.id", "m.make_id")
    .selectAll("g")
    .select(["m.name as model_name", "m.vehicle_class_code", "k.id as make_id", "k.name as make_name"])
    .where("g.id", "=", id)
    .executeTakeFirst();
  if (!g) return null;
  const [powertrains, variants, evidence, siblings] = await Promise.all([
    db.selectFrom("kb.powertrain").selectAll().where("generation_id", "=", id).where("listings", ">", 0)
      .orderBy("listings", "desc").execute(),
    db.selectFrom("kb.commercial_variant").select(["id", "powertrain_id", "country_code", "trim_name", "trim_unknown",
      "sale_year_from", "sale_year_to", "listings"]).where("generation_id", "=", id).where("listings", ">", 0)
      .orderBy("country_code").orderBy("trim_unknown").orderBy("trim_name").execute(),
    evidenceFor("generation", id),
    db.selectFrom("kb.generation").select(["id", "name", "year_from", "year_to", "status"])
      .where("model_id", "=", g.model_id).where("id", "!=", id).where("status", "!=", "rejected").orderBy("id").execute(),
  ]);
  return { g, powertrains, variants, evidence, siblings };
}

export async function powertrain(id: string) {
  await io();
  if (!/^\d+$/.test(id)) return null;
  const p = await getDb()
    .selectFrom("kb.powertrain as p")
    .innerJoin("kb.generation as g", "g.id", "p.generation_id")
    .innerJoin("kb.model as m", "m.id", "g.model_id")
    .innerJoin("kb.make as k", "k.id", "m.make_id")
    .selectAll("p")
    .select(["g.name as generation_name", "k.name as make_name"])
    .where("p.id", "=", id)
    .executeTakeFirst();
  if (!p) return null;
  return { p, evidence: await evidenceFor("powertrain", id) };
}

export async function variant(id: string) {
  await io();
  if (!/^\d+$/.test(id)) return null;
  const db = getDb();
  const v = await db
    .selectFrom("kb.commercial_variant as v")
    .innerJoin("kb.generation as g", "g.id", "v.generation_id")
    .innerJoin("kb.powertrain as p", "p.id", "v.powertrain_id")
    .innerJoin("kb.model as m", "m.id", "g.model_id")
    .innerJoin("kb.make as k", "k.id", "m.make_id")
    .selectAll("v")
    .select([
      "g.name as generation_name", "g.id as generation_id_", "g.seats as generation_seats",
      "p.match_key", "p.engine_displacement_l", "p.engine_cylinders", "p.fuel_type_code",
      "p.transmission_type_code", "p.drivetrain_code", "p.horsepower_hp",
      "k.name as make_name", "m.name as model_name",
    ])
    .where("v.id", "=", id)
    .executeTakeFirst();
  if (!v) return null;
  const [evidence, notes, listings] = await Promise.all([
    evidenceFor("variant", id),
    db.selectFrom("kb.evolution_note").select(["id", "field", "value", "year_from", "note", "source"])
      .where("variant_id", "=", id).orderBy("year_from").orderBy("field").execute(),
    db.selectFrom("kb.listing_level as ll")
      .innerJoin("kb.clean_listing as l", (j) =>
        j.onRef("l.source_site", "=", "ll.source_site").onRef("l.listing_id", "=", "ll.listing_id"))
      .innerJoin("staging.raw_listing as r", (j) =>
        j.onRef("r.source_site", "=", "l.source_site").onRef("r.listing_id", "=", "l.listing_id")
          .onRef("r.version", "=", "l.raw_version"))
      .select(["l.source_site", "l.listing_id", "l.model_year", "l.trim_raw", "l.price", "l.currency_code",
               "l.mileage_km", sql<string>`r.data->>'source_url'`.as("url")])
      .where("ll.variant_id", "=", id)
      .orderBy("l.model_year", "desc")
      .limit(50)
      .execute(),
  ]);
  return { v, evidence, notes, listings };
}
