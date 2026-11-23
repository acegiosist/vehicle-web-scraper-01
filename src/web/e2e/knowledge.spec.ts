import { expect, test } from "@playwright/test";

// The seed (tests/e2e_review_web.py) publishes one variant, Chevrolet Tracker 2020 1.8 L Gasoline
// Manual FWD: six listings agree on 138 hp and disagree on the seats, which opens a review case.
// Files run in name order with one worker, so this runs before review.spec.ts corrects the seats.

test("the knowledge base lists variants filtered by make, model and year", async ({ page }) => {
  await page.goto("/base");
  await expect(page.getByRole("heading", { name: "Base de conocimiento" })).toBeVisible();
  await expect(page.getByText(/^\d+ variantes? · página 1 de 1$/)).toBeVisible();

  // choosing a make submits the form on its own and loads that make's models
  await page.getByLabel("Marca").selectOption({ label: "Chevrolet" });
  await expect(page).toHaveURL(/make=\d+/);
  await expect(page.getByLabel("Modelo")).toBeEnabled();
  await page.getByLabel("Modelo").selectOption({ label: "Tracker" });
  await page.getByLabel("Año").selectOption("2020");
  await page.getByRole("button", { name: "Filtrar" }).click();
  await expect(page).toHaveURL(/model=\d+/);
  await expect(page).toHaveURL(/year=2020/);
  await expect(page.getByText("1 variante · página 1 de 1")).toBeVisible();

  const row = page.getByRole("row", { name: /Tracker/ });
  await expect(row).toContainText("1.8 L Gasoline Manual FWD");
  await expect(row).toContainText("1 caso abierto");
});

test("a variant's sheet shows its values, their source and its open cases", async ({ page }) => {
  await page.goto("/base");
  await page.getByRole("link", { name: "Tracker", exact: true }).first().click();
  await expect(page).toHaveURL(/\/base\/\d+/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Chevrolet Tracker");
  // Next keeps the previous route mounted but hidden (<Activity>): only look at what is visible
  const mech = page.locator("section", { has: page.getByRole("heading", { name: "Ficha técnica" }) });
  const power = mech.getByRole("row", { name: /Potencia/ });
  await expect(power).toContainText("138 hp");
  await expect(power).toContainText("Consenso de anuncios");

  const seats = mech.getByRole("row", { name: /Puestos/ });
  await expect(seats).toContainText("Sin dato");
  await seats.getByRole("link", { name: /En revisión/ }).click();
  await expect(page).toHaveURL(/\/cola\/\d+/);
  await expect(page.getByText("Los anuncios no coinciden").filter({ visible: true }).first()).toBeVisible();
});

test("an unknown or malformed variant shows the not-found page", async ({ page }) => {
  // the sheet streams inside <Suspense>, so the status is already 200: check the page instead
  for (const path of ["/base/999999999", "/base/abc"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { name: "No encontrado" })).toBeVisible();
  }
});
