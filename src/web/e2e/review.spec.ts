import { expect, test } from "@playwright/test";

import { signIn } from "./helpers";

// The seed (tests/e2e_review_web.py) opens three cases: an unknown make "Zzzmotors", its model
// "Thing", and Chevrolet Tracker listings that disagree on the number of seats (3 vs 3).

test.beforeEach(async ({ page }) => signIn(page));

test("the queue lists the open cases in review order", async ({ page }) => {
  await expect(page.getByRole("heading", { name: "Cola de revisión" })).toBeVisible();
  await expect(page.getByText("3 casos · página 1 de 1")).toBeVisible();
  const rows = page.getByRole("row");
  await expect(rows.nth(1)).toContainText("Zzzmotors"); // level 1 (make) first
  await expect(rows.nth(3)).toContainText("Chevrolet Tracker");
});

test("a spec correction is validated, queued and applied by the worker", async ({ page }) => {
  await page.getByRole("link", { name: /Chevrolet Tracker/ }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Chevrolet Tracker");
  // Next keeps the previous route mounted but hidden (<Activity>): only count what is visible
  await expect(page.getByText("Los anuncios no coinciden").filter({ visible: true }).first()).toBeVisible();

  await page.locator('input[name="decision"][value="corrected"]').check();
  const value = page.getByLabel("Valor correcto de puestos");
  await value.fill("99");
  await page.getByRole("button", { name: "Enviar decisión" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Fuera de rango" })).toBeVisible();

  await value.fill("5");
  await page.getByLabel(/Nota/).fill("Ficha del fabricante: 5 puestos");
  await page.getByRole("button", { name: "Enviar decisión" }).click();

  await expect(page.getByText("Aplicada: Corregir por E2E Revisor")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/Decidido: Corregido/)).toContainText("valor: 5");

  await page.goto("/decisiones");
  const row = page.getByRole("row", { name: /Chevrolet Tracker/ });
  await expect(row).toContainText("Aplicada");
  await expect(row).toContainText("Ficha del fabricante: 5 puestos");
});

test("cases with an AI proposal are marked and can be filtered", async ({ page }) => {
  // the seed collects a fake identity batch that proposes the make Zzzmotors
  const makeRow = page.getByRole("row").filter({ hasText: "Zzzmotors" }).filter({ hasText: "Marca" }).first();
  await expect(makeRow.getByText("IA", { exact: true })).toBeVisible();
  await expect(makeRow.getByText("Propuesta de la IA (corrida #1): necesita tu revisión")).toBeVisible();

  await page.getByLabel("Origen").selectOption("ai");
  await page.getByRole("button", { name: "Filtrar" }).click();
  await expect(page).toHaveURL(/origin=ai/);
  await expect(page.getByText("1 caso · página 1 de 1")).toBeVisible();

  await page.getByRole("link", { name: "Zzzmotors", exact: true }).click();
  await expect(page.getByText("Propuesta de la IA · corrida #1")).toBeVisible();
  await expect(page.getByText(/Corrida #1 de Claude, confianza 70 %/)).toBeVisible();
});

test("approving a make with the keyboard", async ({ page }) => {
  await page.getByRole("link", { name: "Zzzmotors", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Zzzmotors");
  await page.locator("body").press("a");
  await expect(page.locator('input[name="decision"][value="approved"]')).toBeChecked();
  await page.locator("body").press("Control+Enter");
  await expect(page.getByText("Aplicada: Aprobar por E2E Revisor")).toBeVisible({ timeout: 20_000 });

  await page.goto("/cola");
  await expect(page.getByRole("heading", { name: "Cola de revisión" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Zzzmotors", exact: true })).toHaveCount(0); // decided: out of the queue
});
