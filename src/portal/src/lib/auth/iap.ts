import { createLocalJWKSet, createRemoteJWKSet, jwtVerify, type JSONWebKeySet, type JWTVerifyGetKey } from "jose";

/**
 * Identity from Google Cloud Identity-Aware Proxy (IAP).
 *
 * IAP signs every request it lets through with an ES256 JWT in `x-goog-iap-jwt-assertion`.
 * Only that signed token is trusted: the unsigned `x-goog-authenticated-user-email` header
 * can be forged by anyone who reaches the service without going through IAP.
 * Checks (IAP's "signed headers" guide): signature against Google's IAP keys, issuer,
 * audience, expiry and issue time with 30 s of skew. The email claim has no namespace prefix.
 */
export const IAP_HEADER = "x-goog-iap-jwt-assertion";
export const IAP_ISSUER = "https://cloud.google.com/iap";
export const IAP_JWKS_URL = "https://www.gstatic.com/iap/verify/public_key-jwk";

/** Cloud Run, App Engine and backend-service audiences as IAP writes them. */
export const IAP_AUDIENCE_RE =
  /^\/projects\/\d+\/(locations\/[a-z0-9-]+\/services\/[A-Za-z0-9_-]+|apps\/[a-z0-9-]+|global\/backendServices\/\d+)$/;

export interface IapIdentity {
  email: string;
  sub: string;
}

export class IapError extends Error {}

const EMAIL_RE = /^[^@\s]+@[^@\s]+$/;

export async function verifyIapAssertion(
  token: string | null | undefined,
  keys: JWTVerifyGetKey,
  audience: string,
): Promise<IapIdentity> {
  if (!token) throw new IapError("La petición no trae la cabecera firmada de IAP");
  let payload;
  try {
    ({ payload } = await jwtVerify(token, keys, {
      issuer: IAP_ISSUER,
      audience,
      algorithms: ["ES256"],
      clockTolerance: 30,
      // IAP tokens live at most 10 minutes (+ skew); also rejects an issue time in the future.
      maxTokenAge: "11 minutes",
      requiredClaims: ["email", "sub", "iat", "exp"],
    }));
  } catch (e) {
    throw new IapError(`Token de IAP no válido: ${e instanceof Error ? e.message : String(e)}`);
  }
  const email = String(payload.email ?? "")
    .trim()
    .toLowerCase();
  if (!EMAIL_RE.test(email)) throw new IapError("El token de IAP no trae un correo");
  return { email, sub: String(payload.sub) };
}

let remoteKeys: JWTVerifyGetKey | undefined;

/** Google's IAP public keys, fetched on demand and cached by jose (refetched on an unknown kid). */
export function googleIapKeys(): JWTVerifyGetKey {
  remoteKeys ??= createRemoteJWKSet(new URL(IAP_JWKS_URL));
  return remoteKeys;
}

export function localKeys(jwks: string): JWTVerifyGetKey {
  let parsed: JSONWebKeySet;
  try {
    parsed = JSON.parse(jwks) as JSONWebKeySet;
  } catch {
    throw new IapError("PORTAL_IAP_JWKS no es un JSON válido");
  }
  return createLocalJWKSet(parsed);
}
