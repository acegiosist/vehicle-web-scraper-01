import "server-only";

import { cookies } from "next/headers";

import { REVIEWER_COOKIE, reviewerSchema } from "./reviewer-schema";

/**
 * Who is deciding. Today the reviewer types a name (local use only, no login); this is the
 * single place to plug real authentication in later (SSO session -> user name).
 */
export async function getReviewer(): Promise<string | null> {
  const raw = (await cookies()).get(REVIEWER_COOKIE)?.value;
  const parsed = reviewerSchema.safeParse(raw);
  return parsed.success ? parsed.data : null;
}
