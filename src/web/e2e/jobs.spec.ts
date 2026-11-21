import { readFileSync } from "node:fs";

import { expect, type Locator, test } from "@playwright/test";

import { signIn } from "./helpers";

// Jobs run by the real worker on the seeded database (tests/e2e_review_web.py): 7 listings.

test.beforeEach(async ({ page }) => signIn(page));

// Next keeps the previous route mounted but hidden (<Activity>): only count what is visible.
const visible = (l: Locator) => l.filter({ visible: true }).first();

test("recalculate from /tareas runs to the end", async ({ page }) => {
  await page.goto("/tareas");
  await page.getByRole("button", { name: "Recalcular todo" }).click();
  await expect(page).toHaveURL(/\/tareas\/\d+$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Recalcular (normalizar + consolidar)");
  await expect(visible(page.getByText("Terminada", { exact: true }))).toBeVisible({ timeout: 30_000 });
  await expect(page.locator("pre")).toContainText("consolidate");
});

test("an export can be downloaded", async ({ page }) => {
  await page.goto("/tareas");
  await page.getByLabel("Formato").selectOption("csv");
  await page.getByRole("button", { name: "Exportar", exact: true }).click();
  await expect(page).toHaveURL(/\/tareas\/\d+$/);
  const link = page.getByRole("link", { name: /Descargar kb_listings\.csv/ });
  await expect(link).toBeVisible({ timeout: 30_000 });
  const [download] = await Promise.all([page.waitForEvent("download"), link.click()]);
  expect(download.suggestedFilename()).toBe("kb_listings.csv");
  const lines = readFileSync(await download.path(), "utf8")
    .replace(/^﻿/, "")
    .trim()
    .split(/\r?\n/);
  expect(lines[0]).toMatch(/^source_site,/);
  expect(lines).toHaveLength(8); // header + 7 listings
});

test("an AI estimate over the spending limit can't be sent", async ({ page }) => {
  // the seed spent US$2 today and the e2e worker's limit is US$1 a day (tests/e2e_review_web.py)
  await page.goto("/tareas");
  await page.getByLabel("Qué").selectOption("specs");
  await page.getByRole("button", { name: "Estimar" }).click();
  await expect(page).toHaveURL(/\/tareas\/\d+$/);
  await expect(visible(page.getByText("Terminada", { exact: true }))).toBeVisible({ timeout: 30_000 });
  const budget = page.getByRole("region", { name: "Presupuesto de IA" });
  await expect(budget).toContainText("Gastado US$ 2.00 de US$ 1.00 · quedan US$ 0.00");
  await expect(budget).toContainText("hoy · se reinicia el");
  await expect(page.getByRole("alert").filter({ hasText: "Se superó el límite de gasto en IA" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Enviar a Claude/ })).toBeDisabled();
});

test("the status page shows the counts", async ({ page }) => {
  await page.goto("/estado");
  await expect(page.getByRole("heading", { name: "Estado de la base" })).toBeVisible();
  const listings = page.locator("dl > div").filter({ hasText: "Anuncios" }).first();
  await expect(listings).toContainText("7");
  await expect(page.getByText("Cobertura", { exact: true })).toBeVisible();
});
