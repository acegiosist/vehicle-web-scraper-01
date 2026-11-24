import { expect, test as base, type Page } from "@playwright/test";
import { importJWK, SignJWT, type JWK } from "jose";

/** Same users as tests/e2e_portal.py seeds (.test is a reserved domain: nobody real). */
export const USERS = {
  lector: "lector@e2e.test",
  revisor: "revisor@e2e.test",
  editor: "editor@e2e.test",
} as const;
export type E2EUser = keyof typeof USERS;

export const AUDIENCE = "/projects/123456789/locations/us-central1/services/omnibase-portal";
export const IAP_HEADER = "x-goog-iap-jwt-assertion";

/** A token like the one IAP signs, with the test key pair from playwright.config.ts. */
export async function iapToken(
  email: string,
  { audience = AUDIENCE, key = process.env.E2E_IAP_PRIVATE_JWK }: { audience?: string; key?: string } = {},
): Promise<string> {
  if (!key) throw new Error("E2E_IAP_PRIVATE_JWK is not set: run through playwright.config.ts");
  const privateKey = await importJWK(JSON.parse(key) as JWK, "ES256");
  return new SignJWT({ email })
    .setProtectedHeader({ alg: "ES256", kid: "e2e" })
    .setIssuer("https://cloud.google.com/iap")
    .setAudience(audience)
    .setSubject(`accounts.google.com:${email}`)
    .setIssuedAt()
    .setExpirationTime("10m")
    .sign(privateKey);
}

/**
 * `test.use({ as: "editor" })` sends that user's signed header on every request of the page
 * (navigations, server actions, refreshes), as IAP does. A fresh token per test: IAP tokens
 * live 10 minutes, less than a build plus a run.
 */
export const test = base.extend<{ as: E2EUser | null }>({
  as: [null, { option: true }],
  // (`provide`, not `use`: the React hooks lint rule would take it for React's use())
  extraHTTPHeaders: async ({ as, extraHTTPHeaders }, provide) => {
    await provide(as ? { ...extraHTTPHeaders, [IAP_HEADER]: await iapToken(USERS[as]) } : extraHTTPHeaders);
  },
});

export { expect };

/**
 * Waits until the worker applied (or failed) the newest request in the page's "Cambios recientes".
 * Visible only: Next keeps the previous page of the same route mounted, hidden, after a navigation.
 */
export async function expectLatestAction(page: Page, status: "Aplicada" | "Falló", timeout = 30_000) {
  await expect(page.getByTestId("recent-action").filter({ visible: true }).first()).toContainText(status, { timeout });
}
