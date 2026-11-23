import "server-only";

import { sql } from "kysely";

import { getDb } from "@/lib/db";

/** Listings with their current version from staging (the scraped record as JSON). */
export function listingsWithRaw() {
  return getDb()
    .selectFrom("kb.listing as l")
    .innerJoin("staging.raw_listing as r", (j) =>
      j
        .onRef("r.source_site", "=", "l.source_site")
        .onRef("r.listing_id", "=", "l.listing_id")
        .on("r.valid_to", "is", null),
    );
}

export type ListingsQuery = ReturnType<typeof listingsWithRaw>;

/** The most recent ``limit`` listings of ``q`` (what ListingsTable shows), the value each one
 *  reports for ``field``, and how many there are in total. */
export async function listingPage(q: ListingsQuery, field: string | null, limit: number) {
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
