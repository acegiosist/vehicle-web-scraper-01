import { exportJWK, generateKeyPair, SignJWT, type CryptoKey } from "jose";
import { beforeAll, describe, expect, it } from "vitest";

import { readAuthConfig } from "./config";
import { IAP_ISSUER, IapError, localKeys, verifyIapAssertion } from "./iap";
import { hasRole } from "./roles";

const AUD = "/projects/123456789/locations/us-central1/services/omnibase-portal";
let priv: CryptoKey;
let other: CryptoKey;
let jwks: string;

beforeAll(async () => {
  const pair = await generateKeyPair("ES256");
  priv = pair.privateKey;
  other = (await generateKeyPair("ES256")).privateKey;
  jwks = JSON.stringify({ keys: [{ ...(await exportJWK(pair.publicKey)), kid: "test", alg: "ES256" }] });
});

function token(
  claims: Record<string, unknown> = {},
  opts: { key?: CryptoKey; aud?: string; iss?: string; iat?: number; exp?: number } = {},
) {
  const now = Math.floor(Date.now() / 1000);
  return new SignJWT({ email: "Ana@Empresa.com", ...claims })
    .setProtectedHeader({ alg: "ES256", kid: "test" })
    .setIssuer(opts.iss ?? IAP_ISSUER)
    .setAudience(opts.aud ?? AUD)
    .setSubject("accounts.google.com:1234")
    .setIssuedAt(opts.iat ?? now)
    .setExpirationTime(opts.exp ?? now + 600)
    .sign(opts.key ?? priv);
}

describe("verifyIapAssertion", () => {
  it("accepts a token signed by the IAP keys and lowercases the email", async () => {
    const id = await verifyIapAssertion(await token(), localKeys(jwks), AUD);
    expect(id).toEqual({ email: "ana@empresa.com", sub: "accounts.google.com:1234" });
  });

  const now = () => Math.floor(Date.now() / 1000);
  const bad: [string, () => Promise<string | null>][] = [
    ["no header", async () => null],
    ["another key", () => token({}, { key: other })],
    ["wrong audience", () => token({}, { aud: "/projects/1/apps/otro" })],
    ["wrong issuer", () => token({}, { iss: "https://example.com" })],
    ["expired", () => token({}, { iat: now() - 3600, exp: now() - 60 })],
    ["issued in the future", () => token({}, { iat: now() + 3600, exp: now() + 4000 })],
    ["no email", () => token({ email: undefined })],
    ["not a JWT", async () => "abc.def.ghi"],
  ];
  it.each(bad)("rejects: %s", async (_name, make) => {
    await expect(verifyIapAssertion(await make(), localKeys(jwks), AUD)).rejects.toBeInstanceOf(IapError);
  });

  it("tolerates 30 s of clock skew", async () => {
    const t = await token({}, { iat: now() - 620, exp: now() - 20 });
    await expect(verifyIapAssertion(t, localKeys(jwks), AUD)).resolves.toMatchObject({ email: "ana@empresa.com" });
  });
});

describe("readAuthConfig", () => {
  it("defaults to IAP and needs a well-formed audience", () => {
    expect(() => readAuthConfig({})).toThrow(/PORTAL_IAP_AUDIENCE/);
    expect(() => readAuthConfig({ PORTAL_IAP_AUDIENCE: "omnibase" })).toThrow(/PORTAL_IAP_AUDIENCE/);
    expect(readAuthConfig({ PORTAL_IAP_AUDIENCE: AUD }).mode).toBe("iap");
    expect(readAuthConfig({ PORTAL_IAP_AUDIENCE: "/projects/1/global/backendServices/42" }).mode).toBe("iap");
  });

  it("allows dev mode only outside production and Cloud Run", () => {
    const dev = { PORTAL_AUTH: "dev", PORTAL_DEV_USER: "Eva@Empresa.com", NODE_ENV: "development" };
    expect(readAuthConfig(dev)).toEqual({ mode: "dev", email: "eva@empresa.com" });
    expect(() => readAuthConfig({ ...dev, NODE_ENV: "production" })).toThrow(/producción/);
    expect(() => readAuthConfig({ ...dev, K_SERVICE: "omnibase-portal" })).toThrow(/Cloud Run/);
    expect(() => readAuthConfig({ ...dev, PORTAL_DEV_USER: "" })).toThrow(/PORTAL_DEV_USER/);
    expect(() => readAuthConfig({ PORTAL_AUTH: "none" })).toThrow(/iap o dev/);
  });

  it("accepts test keys, but never on Cloud Run", () => {
    expect(readAuthConfig({ PORTAL_IAP_AUDIENCE: AUD, PORTAL_IAP_JWKS: jwks }).mode).toBe("iap");
    expect(() => readAuthConfig({ PORTAL_IAP_AUDIENCE: AUD, PORTAL_IAP_JWKS: jwks, K_SERVICE: "x" })).toThrow(
      /Cloud Run/,
    );
  });
});

describe("hasRole", () => {
  it("orders lector < revisor < editor", () => {
    expect(hasRole("editor", "revisor")).toBe(true);
    expect(hasRole("revisor", "revisor")).toBe(true);
    expect(hasRole("lector", "revisor")).toBe(false);
    expect(hasRole(null, "lector")).toBe(false);
  });
});
