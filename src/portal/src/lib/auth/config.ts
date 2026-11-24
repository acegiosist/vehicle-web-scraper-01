import type { JWTVerifyGetKey } from "jose";

import { IAP_AUDIENCE_RE, googleIapKeys, localKeys } from "./iap";

/**
 * How the portal learns who is using it, from the environment:
 *
 * - `PORTAL_AUTH=iap` (default): verify IAP's signed header. `PORTAL_IAP_AUDIENCE` is required
 *   (e.g. `/projects/123456789/locations/us-central1/services/omnibase-portal`).
 *   `PORTAL_IAP_JWKS` (a JSON key set) replaces Google's keys, for automated tests only: it is
 *   refused on Cloud Run.
 * - `PORTAL_AUTH=dev`: local development without IAP. `PORTAL_DEV_USER` is the identity.
 *   Refused in production (`NODE_ENV=production`) and on Cloud Run (`K_SERVICE` set), so a
 *   misconfiguration can't open the portal without authentication.
 */
export type AuthConfig = { mode: "iap"; audience: string; keys: JWTVerifyGetKey } | { mode: "dev"; email: string };

export class AuthConfigError extends Error {}

type Env = Record<string, string | undefined>;

export function readAuthConfig(env: Env = process.env): AuthConfig {
  const mode = (env.PORTAL_AUTH ?? "iap").trim().toLowerCase();
  const onCloudRun = Boolean(env.K_SERVICE);
  if (mode === "dev") {
    if (env.NODE_ENV === "production" || onCloudRun) {
      throw new AuthConfigError("PORTAL_AUTH=dev no se permite en producción ni en Cloud Run: usar IAP");
    }
    const email = (env.PORTAL_DEV_USER ?? "").trim().toLowerCase();
    if (!/^[^@\s]+@[^@\s]+$/.test(email)) {
      throw new AuthConfigError("PORTAL_AUTH=dev necesita PORTAL_DEV_USER con un correo");
    }
    return { mode: "dev", email };
  }
  if (mode !== "iap") throw new AuthConfigError(`PORTAL_AUTH=${mode}: usar iap o dev`);
  const audience = (env.PORTAL_IAP_AUDIENCE ?? "").trim();
  if (!IAP_AUDIENCE_RE.test(audience)) {
    throw new AuthConfigError(
      "Falta PORTAL_IAP_AUDIENCE con el formato de IAP, p. ej. /projects/123456789/locations/REGION/services/SERVICIO",
    );
  }
  if (env.PORTAL_IAP_JWKS) {
    if (onCloudRun) throw new AuthConfigError("PORTAL_IAP_JWKS es solo para pruebas: no se permite en Cloud Run");
    return { mode: "iap", audience, keys: localKeys(env.PORTAL_IAP_JWKS) };
  }
  return { mode: "iap", audience, keys: googleIapKeys() };
}

let cached: AuthConfig | undefined;

/** The process's config, read once. */
export function authConfig(): AuthConfig {
  cached ??= readAuthConfig();
  return cached;
}
