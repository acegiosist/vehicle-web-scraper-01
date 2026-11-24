import { generateKeyPairSync } from "node:crypto";
import path from "node:path";

import { defineConfig } from "@playwright/test";

import { AUDIENCE } from "./e2e/fixtures";

/**
 * End-to-end tests (`pnpm test:e2e`): the production build in IAP mode against a throwaway
 * database, with the real `kb worker` applying what the pages queue.
 *
 * - `tests/e2e_portal.py` (repository root) recreates that database in the test container
 *   (port 55441, see its docstring), seeds it and runs the worker; Playwright waits for its
 *   READY line. Web servers start before globalSetup, so the database is prepared there.
 * - The portal connects with the least-privilege role, like on GCP.
 * - IAP is simulated with a key pair made here: the portal trusts its public half
 *   (PORTAL_IAP_JWKS) and e2e/fixtures.ts signs each test's token with the private half.
 *   The config is loaded again in every test worker; the key travels in the environment so
 *   all processes share the same pair.
 */
if (!process.env.E2E_IAP_PRIVATE_JWK) {
  const { privateKey, publicKey } = generateKeyPairSync("ec", { namedCurve: "P-256" });
  process.env.E2E_IAP_PRIVATE_JWK = JSON.stringify(privateKey.export({ format: "jwk" }));
  process.env.E2E_IAP_JWKS = JSON.stringify({
    keys: [{ ...publicKey.export({ format: "jwk" }), kid: "e2e", alg: "ES256", use: "sig" }],
  });
}

const PORT = 3100;
const repoRoot = path.resolve(__dirname, "../..");
const python =
  process.env.E2E_PYTHON ??
  path.join(repoRoot, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const portalDatabaseUrl =
  process.env.E2E_PORTAL_DATABASE_URL ?? "postgresql://omnibase_portal_e2e:e2e@localhost:55441/omnibase_e2e";

export default defineConfig({
  testDir: "./e2e",
  // One database shared by every test, which change it in order: no parallelism.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    // Windows: the installed Edge; elsewhere Playwright's Chromium.
    ...(process.platform === "win32" ? { channel: "msedge" } : {}),
    trace: "retain-on-failure",
  },
  webServer: [
    {
      name: "worker",
      command: `"${python}" tests/e2e_portal.py`,
      cwd: repoRoot,
      wait: { stdout: /e2e worker ready/ },
      stdout: "pipe",
      timeout: 120_000,
      reuseExistingServer: false,
    },
    {
      name: "portal",
      command: `pnpm build && pnpm exec next start -H 127.0.0.1 -p ${PORT}`,
      url: `http://127.0.0.1:${PORT}/api/salud`,
      timeout: 300_000,
      reuseExistingServer: false,
      env: {
        PORTAL_DATABASE_URL: portalDatabaseUrl,
        PORTAL_AUTH: "iap",
        PORTAL_IAP_AUDIENCE: AUDIENCE,
        PORTAL_IAP_JWKS: process.env.E2E_IAP_JWKS!,
        // never the developer's own settings
        PORTAL_DEV_USER: "",
      },
    },
  ],
});
