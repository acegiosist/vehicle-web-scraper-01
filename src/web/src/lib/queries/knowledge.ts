import "server-only";

import { sql } from "kysely";
import { io } from "next/cache";

import { getDb } from "@/lib/db";
import { ID_PATTERN, type KnowledgeFilters, PAGE_SIZE } from "@/lib/filters";
import { listingPage, listingsWithRaw } from "@/lib/queries/listings";

// The knowledge base browser (/base): every variant, whatever its status, read-only.

/** Variants with their make and model, narrowed by the list filters. */
function filteredVariants(f: KnowledgeFilters) {
  let q = getDb()
    .selectFrom("kb.variant as v")
    .innerJoin("kb.model as md", "md.id", "v.model_id")
    .innerJoin("kb.make as mk", "mk.id", "md.make_id");
  if (f.make) q = q.where("mk.id", "=", f.make);
  if (f.model) q = q.where("md.id", "=", f.model);
  if (f.year) q = q.where("v.model_year", "=", f.year);
  return q;
}

// Open review cases about a variant: its specs and its cross-checks (entity_id is the variant id).
const OPEN_CASE_TYPES = ["spec", "variant"];

export async function listVariants(filters: KnowledgeFilters) {
  await io();
  const page = filters.page ?? 1;
  const base = filteredVariants(filters);
  const [rows, total] = await Promise.all([
    base
      .leftJoin("kb.trim as t", "t.id", "v.trim_id")
      .leftJoin("kb.variant_spec as vs", "vs.variant_id", "v.id")
      .select([
        "v.id",
        "mk.name as make_name",
        "md.name as model_name",
        "t.name as trim_name",
        "v.model_year",
        "v.engine_displacement_l",
        "v.fuel_type",
        "v.transmission_type",
        "v.drivetrain",
        "v.status",
        "vs.body_style",
        // correlated subqueries: they only run for the rows of the page
        sql<number>`(SELECT coalesce(sum(vm.listings_seen), 0)::int FROM kb.variant_market vm WHERE vm.variant_id = v.id)`.as(
          "listings",
        ),
        sql<
          string[]
        >`ARRAY(SELECT vm.country FROM kb.variant_market vm WHERE vm.variant_id = v.id ORDER BY vm.country)`.as(
          "countries",
        ),
        sql<number>`(SELECT count(*)::int FROM kb.review_item ri
                     WHERE ri.status = 'pending' AND ri.entity_type IN ('spec', 'variant') AND ri.entity_id = v.id)`.as(
          "open_cases",
        ),
      ])
      .orderBy("mk.name")
      .orderBy("md.name")
      .orderBy("v.model_year", "desc")
      .orderBy("t.name", (ob) => ob.asc().nullsFirst())
      .orderBy("v.id")
      .limit(PAGE_SIZE)
      .offset((page - 1) * PAGE_SIZE)
      .execute(),
    base.select((eb) => eb.fn.countAll<string>().as("n")).executeTakeFirstOrThrow(),
  ]);
  return { rows, total: Number(total.n), page, pageCount: Math.max(1, Math.ceil(Number(total.n) / PAGE_SIZE)) };
}

export type VariantRow = Awaited<ReturnType<typeof listVariants>>["rows"][number];

/** Values for the filter selects: makes with variants, the models of the chosen make, and the
 *  model years within the chosen make/model. */
export async function knowledgeFilterOptions(filters: KnowledgeFilters) {
  await io();
  const db = getDb();
  const [makes, models, years] = await Promise.all([
    db
      .selectFrom("kb.make as mk")
      .select(["mk.id", "mk.name"])
      .where(
        sql<boolean>`EXISTS (SELECT 1 FROM kb.model md JOIN kb.variant v ON v.model_id = md.id WHERE md.make_id = mk.id)`,
      )
      .orderBy("mk.name")
      .execute(),
    filters.make
      ? db
          .selectFrom("kb.model as md")
          .select(["md.id", "md.name"])
          .where("md.make_id", "=", filters.make)
          .where(sql<boolean>`EXISTS (SELECT 1 FROM kb.variant v WHERE v.model_id = md.id)`)
          .orderBy("md.name")
          .execute()
      : Promise.resolve([]),
    filteredVariants({ make: filters.make, model: filters.model })
      .select("v.model_year")
      .distinct()
      .orderBy("v.model_year", "desc")
      .execute(),
  ]);
  return { makes, models, years: years.map((y) => y.model_year) };
}

/** A variant with its identity, its published sheets and the markets it was seen in. */
export async function getVariant(id: string) {
  await io();
  if (!ID_PATTERN.test(id)) return null;
  const db = getDb();
  const variant = await db
    .selectFrom("kb.variant as v")
    .innerJoin("kb.model as md", "md.id", "v.model_id")
    .innerJoin("kb.make as mk", "mk.id", "md.make_id")
    .leftJoin("kb.trim as t", "t.id", "v.trim_id")
    .select([
      "v.id",
      "v.model_year",
      "v.engine_displacement_l",
      "v.fuel_type",
      "v.transmission_type",
      "v.drivetrain",
      "v.status",
      "v.verified_by",
      "mk.id as make_id",
      "mk.name as make_name",
      "mk.status as make_status",
      "mk.verified_by as make_verified_by",
      "md.id as model_id",
      "md.name as model_name",
      "md.status as model_status",
      "md.verified_by as model_verified_by",
      "md.vehicle_class",
      "md.year_from",
      "md.year_to",
      "t.name as trim_name",
      "t.status as trim_status",
      "t.verified_by as trim_verified_by",
    ])
    .where("v.id", "=", id)
    .executeTakeFirst();
  if (!variant) return null;
  const [spec, markets, marketSpecs] = await Promise.all([
    db.selectFrom("kb.variant_spec").selectAll().where("variant_id", "=", id).executeTakeFirst(),
    db
      .selectFrom("kb.variant_market")
      .select(["country", "listings_seen"])
      .where("variant_id", "=", id)
      .orderBy("country")
      .execute(),
    db.selectFrom("kb.variant_market_spec").selectAll().where("variant_id", "=", id).orderBy("country").execute(),
  ]);
  return {
    variant,
    spec: (spec ?? null) as Record<string, unknown> | null,
    markets,
    marketSpecs: marketSpecs as (Record<string, unknown> & { country: string })[],
  };
}

export type VariantSheet = NonNullable<Awaited<ReturnType<typeof getVariant>>>;

/** Every candidate value collected for the variant (listings, siblings, AI, people). */
export async function variantEvidence(id: string) {
  await io();
  return getDb()
    .selectFrom("kb.spec_evidence")
    .select([
      "id",
      "field",
      "country",
      "value",
      "source_kind",
      "status",
      "support_count",
      "agreement",
      "confidence",
      "sites",
      "reason",
    ])
    .where("variant_id", "=", id)
    .orderBy("field")
    .orderBy("country")
    .orderBy("id")
    .execute();
}

export type VariantEvidence = Awaited<ReturnType<typeof variantEvidence>>[number];

/** Review cases still open about the variant's specs or about the variant itself. */
export async function variantOpenCases(id: string) {
  await io();
  return getDb()
    .selectFrom("kb.review_queue")
    .select(["id", "field", "country", "issue", "in_queue", "from_ai"])
    .where("entity_type", "in", OPEN_CASE_TYPES)
    .where("entity_id", "=", id)
    .where("status", "=", "pending")
    .orderBy("level")
    .orderBy("id")
    .execute();
}

export type VariantCase = Awaited<ReturnType<typeof variantOpenCases>>[number];

/** The latest changes to the variant's published values. */
export async function variantHistory(id: string, limit = 50) {
  await io();
  return getDb()
    .selectFrom("kb.spec_history")
    .select(["id", "field", "country", "old_value", "new_value", "old_source", "new_source", "reason", "changed_at"])
    .where("variant_id", "=", id)
    .orderBy("changed_at", "desc")
    .orderBy("id", "desc")
    .limit(limit)
    .execute();
}

/** The listings matched to the variant (most recent first). */
export async function variantListings(id: string, limit = 25) {
  await io();
  return listingPage(listingsWithRaw().where("l.variant_id", "=", id), null, limit);
}
