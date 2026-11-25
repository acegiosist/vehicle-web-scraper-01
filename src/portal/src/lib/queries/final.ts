import "server-only";

import { io } from "next/cache";

import { getDb } from "@/lib/db";
import type { IdentityFilters } from "@/lib/vehicle-identity";

const escapeLike = (s: string) => `%${s.replace(/[\\%_]/g, (m) => `\\${m}`)}%`;

/** A page of kb.vehicle_identity (filled by `kb build`) and how many sheets match. */
export async function identityList(f: IdentityFilters) {
  await io();
  let q = getDb().selectFrom("kb.vehicle_identity");
  if (f.country) q = q.where("country_code", "=", f.country);
  if (f.status === "verificadas") q = q.where("variant_status", "=", "verified");
  else if (f.status === "provisionales") q = q.where("variant_status", "=", "provisional");
  if (f.knownTrim) q = q.where("trim_unknown", "=", false);
  if (f.q) {
    // each word must appear in the make, the model, the generation or the trim ("kia sportage gt")
    for (const word of f.q.split(/\s+/).slice(0, 5)) {
      const like = escapeLike(word);
      q = q.where((eb) => eb.or([eb("make", "ilike", like), eb("model", "ilike", like),
                                 eb("generation_name", "ilike", like), eb("trim", "ilike", like)]));
    }
  }
  const [rows, total] = await Promise.all([
    q
      .select([
        "variant_id", "country_code", "make", "model", "generation_name", "year_from", "year_to", "trim",
        "trim_unknown", "sale_year_from", "sale_year_to", "engine_displacement_l", "fuel_type", "transmission_type",
        "drivetrain", "horsepower_hp", "listings", "variant_status",
      ])
      .orderBy("make")
      .orderBy("model")
      .orderBy("generation_name")
      .orderBy("country_code")
      .orderBy("trim_unknown")
      .orderBy("trim")
      .orderBy("variant_id")
      .limit(f.size)
      .offset((f.page - 1) * f.size)
      .execute(),
    q.select((eb) => eb.fn.countAll<string>().as("n")).executeTakeFirstOrThrow(),
  ]);
  return { rows, total: Number(total.n) };
}

/** Countries that have sheets, for the filter. */
export async function identityCountries() {
  await io();
  const rows = await getDb().selectFrom("kb.vehicle_identity").select("country_code").distinct()
    .orderBy("country_code").execute();
  return rows.map((r) => r.country_code);
}

/** One vehicle's sheet and its most recent listings (their final records), or undefined. */
export async function identity(variantId: string) {
  await io();
  if (!/^\d+$/.test(variantId)) return undefined;
  const db = getDb();
  const [sheet, listings] = await Promise.all([
    db.selectFrom("kb.vehicle_identity").selectAll().where("variant_id", "=", variantId).executeTakeFirst(),
    db.selectFrom("kb.final_listing")
      .select(["source_site", "listing_id", "source_url", "model_year", "price", "currency", "mileage_km"])
      .where("variant_id", "=", variantId)
      .orderBy("listed_at", (ob) => ob.desc().nullsLast())
      .orderBy("listing_id")
      .limit(50)
      .execute(),
  ]);
  return sheet ? { sheet, listings } : undefined;
}

/** One listing's final record, or undefined when it has none (excluded, or not built yet). */
export async function finalRecord(site: string, listingId: string) {
  await io();
  return getDb()
    .selectFrom("kb.final_listing")
    .selectAll()
    .where("source_site", "=", site)
    .where("listing_id", "=", listingId)
    .executeTakeFirst();
}
