import "server-only";

import { cache } from "react";
import { headers } from "next/headers";

import { getDb } from "@/lib/db";

import { authConfig } from "./config";
import { IAP_HEADER, IapError, verifyIapAssertion } from "./iap";
import { hasRole, type Role } from "./roles";

export interface CurrentUser {
  email: string;
  name: string | null;
  /** null: authenticated, but not in kb.app_user (or inactive): no access. */
  role: Role | null;
}

/**
 * Who is making this request, once per request. In IAP mode the signed header is verified
 * here, in the server code that reads data, not only in proxy.ts (which is an early check).
 * Throws IapError when the request isn't authenticated.
 */
export const getCurrentUser = cache(async (): Promise<CurrentUser> => {
  // Request data first: it keeps this out of the prerendered shell (and out of `next build`).
  const requestHeaders = await headers();
  const cfg = authConfig();
  let email: string;
  if (cfg.mode === "dev") {
    email = cfg.email;
  } else {
    email = (await verifyIapAssertion(requestHeaders.get(IAP_HEADER), cfg.keys, cfg.audience)).email;
  }
  const row = await getDb()
    .selectFrom("kb.app_user")
    .select(["name", "role"])
    .where("email", "=", email)
    .where("active", "=", true)
    .executeTakeFirst();
  return { email, name: row?.name ?? null, role: (row?.role as Role | undefined) ?? null };
});

/** The current user if they have at least `needed`, else null (the page shows "sin acceso"). */
export async function userWithRole(needed: Role): Promise<CurrentUser | null> {
  try {
    const user = await getCurrentUser();
    return hasRole(user.role, needed) ? user : null;
  } catch (e) {
    if (e instanceof IapError) return null;
    throw e;
  }
}
