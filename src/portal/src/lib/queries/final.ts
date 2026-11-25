import "server-only";

import { io } from "next/cache";

import { getDb } from "@/lib/db";
import type { FinalFilters } from "@/lib/final-listing";

const escapeLike = (s: string) => `%${s.replace(/[\\%_]/g, (m) => `\\${m}`)}%`;

/** A page of kb.final_listing (filled by `kb build`) and how many records match. */
export async function finalList(f: FinalFilters) {
  await io();
  let q = getDb().selectFrom("kb.final_listing");
  if (f.country) q = q.where("country_code", "=", f.country);
  if (f.status === "asignados") q = q.where("variant_id", "is not", null);
  else if (f.status === "sin-asignar") q = q.where("variant_id", "is", null);
  else if (f.status) q = q.where("unassigned_reason", "=", f.status);
  if (f.year) q = q.where("model_year", "=", f.year);
  if (f.q) {
    // each word must appear in the make, the model or the trim ("kia sportage gt")
    for (const word of f.q.split(/\s+/).slice(0, 5)) {
      const like = escapeLike(word);
      q = q.where((eb) => eb.or([eb("make", "ilike", like), eb("model", "ilike", like), eb("trim", "ilike", like)]));
    }
  }
  const [rows, total] = await Promise.all([
    q
      .select([
        "source_site", "listing_id", "country_code", "make", "model", "trim", "model_year", "fuel_type",
        "transmission_type", "horsepower_hp", "price", "currency", "mileage_km", "variant_id", "unassigned_reason",
      ])
      .orderBy("make")
      .orderBy("model")
      .orderBy("model_year", "desc")
      .orderBy("source_site")
      .orderBy("listing_id")
      .limit(f.size)
      .offset((f.page - 1) * f.size)
      .execute(),
    q.select((eb) => eb.fn.countAll<string>().as("n")).executeTakeFirstOrThrow(),
  ]);
  return { rows, total: Number(total.n) };
}

/** Countries that have records, for the filter. */
export async function finalCountries() {
  await io();
  const rows = await getDb().selectFrom("kb.final_listing").select("country_code").distinct().orderBy("country_code")
    .execute();
  return rows.map((r) => r.country_code);
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
