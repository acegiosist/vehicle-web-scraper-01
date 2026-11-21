import { defineConfig } from "@playwright/test";

// End-to-end: a throwaway database + the real Python worker + a production build of the site.
//   KB_TEST_DATABASE_URL=postgresql://kb:kbtest@localhost:55432/kb pnpm test:e2e
// tests/e2e_review_web.py (repo root) recreates the database `kb_e2e_review` on that server.
const admin = process.env.KB_TEST_DATABASE_URL;
if (!admin) throw new Error("Set KB_TEST_DATABASE_URL (a Postgres where this user may CREATE DATABASE)");
const e2eUrl = admin.replace(/\/[^/?]+(\?.*)?$/, "/kb_e2e_review$1");

const isWindows = process.platform === "win32";
const python = process.env.PYTHON ?? (isWindows ? "..\\..\\.venv\\Scripts\\python.exe" : "../../.venv/bin/python");
const PORT = 3100;

export default defineConfig({
  testDir: "e2e",
  workers: 1, // one shared database
  timeout: 60_000,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    // Edge ships with Windows: no browser download needed. Elsewhere: `pnpm exec playwright install chromium`.
    channel: process.env.PW_CHANNEL ?? (isWindows ? "msedge" : undefined),
    trace: "retain-on-failure",
  },
  webServer: [
    {
      name: "worker",
      command: `${python} ../../tests/e2e_review_web.py`,
      env: { KB_TEST_DATABASE_URL: admin },
      wait: { stderr: /listening on kb_review_decision/ },
      timeout: 120_000,
    },
    {
      name: "web",
      command: `pnpm build && pnpm exec next start -H 127.0.0.1 -p ${PORT}`,
      url: `http://127.0.0.1:${PORT}/cola`,
      // overrides .env.local. The send form is shown, but nothing can be sent: the e2e worker has
      // KB_ALLOW_WEB_AI_SUBMIT off and a spending limit the seed already exceeded.
      env: { REVIEW_WEB_DATABASE_URL: e2eUrl, KB_WEB_AI_SUBMIT: "true" },
      timeout: 300_000,
    },
  ],
});
