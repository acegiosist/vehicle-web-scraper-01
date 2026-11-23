import { expect, test } from "@playwright/test";

import { signIn } from "./helpers";

// The seed (tests/e2e_review_web.py) has two AI runs not collected: #2 still processing at
// Anthropic and #3 finished (4 answers, 1 error). The e2e worker's fake Anthropic marks #3
// 'ended' on its first check, right after it starts; collecting it needs no network.

test.beforeEach(async ({ page }) => signIn(page));

test("a finished AI batch is announced on every page and collected from the notice", async ({ page }) => {
  const notice = page.getByRole("region", { name: "Avisos de IA" });
  await expect(async () => {
    await page.goto("/cola");
    await expect(notice.getByText("El lote de IA #3 terminó")).toBeVisible({ timeout: 1_000 });
  }).toPass({ timeout: 30_000 });
  await expect(notice).toContainText(/identidad · 4 de 5 correctas, 1 con error · terminó hace \d+ min/);
  await expect(notice).toContainText(/Lote de IA #2 \(fichas, .*\) en proceso en Claude · enviado hace/);

  await page.goto("/base"); // the notice is in the layout: every page shows it
  await expect(notice.getByText("El lote de IA #3 terminó")).toBeVisible();

  await notice.getByRole("button", { name: "Recoger resultados" }).click();
  await expect(page).toHaveURL(/\/tareas\/\d+$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("IA: recoger resultados");
  await expect(page.getByText("Terminada", { exact: true }).filter({ visible: true }).first()).toBeVisible({
    timeout: 30_000,
  });

  await page.goto("/tareas");
  await expect(notice.getByText("El lote de IA #3 terminó")).toHaveCount(0); // collected: no more notice
  await expect(notice).toContainText("Lote de IA #2"); // still processing
  const runs = page.getByRole("region", { name: "Lotes de IA" });
  await expect(runs.getByRole("row", { name: /#3 · identidad/ })).toContainText("Recogida");
  await expect(runs.getByRole("row", { name: /#2 · fichas/ })).toContainText("En proceso en Claude");
});
