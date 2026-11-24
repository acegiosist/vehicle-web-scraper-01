import { generateKeyPairSync } from "node:crypto";

import { expect, expectLatestAction, iapToken, IAP_HEADER, test, USERS } from "./fixtures";

/**
 * The portal end to end, against the database tests/e2e_portal.py seeds:
 * Hyundai Creta and Kia Sportage (8 listings each, engine change -> a proposed generation split
 * each) and Renault Zoe (1 listing -> weak_model). The tests run in order and share that data:
 * the reviewer approves the Creta split, the editor cuts the Sportage by hand, then recalculates
 * and both move their listings.
 */
test.describe.configure({ mode: "serial" });

test.describe("sin identidad válida", () => {
  test("sin la cabecera de IAP: 401, salvo la comprobación de salud", async ({ playwright, baseURL }) => {
    const anon = await playwright.request.newContext({ baseURL });
    expect((await anon.get("/")).status()).toBe(401);
    expect((await anon.get("/revision")).status()).toBe(401);
    expect((await anon.get("/api/salud")).status()).toBe(200);
    await anon.dispose();
  });

  const otherKey = JSON.stringify(
    generateKeyPairSync("ec", { namedCurve: "P-256" }).privateKey.export({ format: "jwk" }),
  );
  const cases: [string, () => Promise<Record<string, string>>][] = [
    [
      "cabecera de correo falsificada con un token basura",
      async () => ({ [IAP_HEADER]: "no-es-un-jwt", "x-goog-authenticated-user-email": `accounts.google.com:${USERS.editor}` }),
    ],
    ["token firmado con otra llave", async () => ({ [IAP_HEADER]: await iapToken(USERS.editor, { key: otherKey }) })],
    [
      "token para otra audiencia",
      async () => ({ [IAP_HEADER]: await iapToken(USERS.editor, { audience: "/projects/1/locations/x/services/otro" }) }),
    ],
    ["token válido de alguien que no está en Usuarios", async () => ({ [IAP_HEADER]: await iapToken("nadie@e2e.test") })],
  ];
  for (const [name, headers] of cases) {
    test(`${name}: sin acceso`, async ({ page }) => {
      await page.setExtraHTTPHeaders(await headers());
      await page.goto("/");
      await expect(page.getByRole("main").getByText("Sin acceso")).toBeVisible();
      await expect(page.getByRole("button", { name: "Recalcular ahora" })).toHaveCount(0);
    });
  }
});

test.describe("lector", () => {
  test.use({ as: "lector" });

  test("ve todo y no ve formularios", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Estado de la base" })).toBeVisible();
    await expect(page.getByTestId("recalc-status").filter({ visible: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Recalcular ahora" })).toHaveCount(0);

    await page.goto("/revision?tipo=weak_model");
    await page.getByRole("link", { name: /Zoe/ }).click();
    await expect(page.getByTestId("case-entity").filter({ visible: true })).toContainText("Zoe");
    await expect(page.getByRole("main").getByText("Sin acceso")).toBeVisible();
    await expect(page.getByRole("button", { name: "Enviar decisión" })).toHaveCount(0);

    await page.goto("/base");
    await page.getByRole("link", { name: "Kia" }).click();
    await page.getByRole("link", { name: "Sportage (SUV)", exact: true }).click();
    await expect(page.getByTestId("generation-name").filter({ visible: true })).toContainText("Kia Sportage (SUV)");
    await expect(page.getByTestId("split-form").filter({ visible: true })).toHaveCount(0);
    await expect(page.getByText("Editar")).toHaveCount(0);

    await page.goto("/usuarios");
    await expect(page.getByRole("main").getByText("Sin acceso")).toBeVisible();
    await expect(page.getByTestId("user-form").filter({ visible: true })).toHaveCount(0);
  });
});

test.describe("revisor", () => {
  test.use({ as: "revisor" });

  test("decide un caso y el worker lo aplica; no recalcula ni edita", async ({ page }) => {
    await page.goto("/revision?tipo=generation_split");
    await page.getByRole("link", { name: /Creta/ }).click();
    await expect(page.getByTestId("case-entity").filter({ visible: true })).toContainText("Creta");
    await page.getByRole("radio", { name: /Aprobar/ }).check();
    await page.getByLabel("Nota (opcional)").fill("e2e: el motor cambia en 2021");
    await page.getByRole("button", { name: "Enviar decisión" }).click();
    // The page refreshes while the request is queued; the worker applies it (often before the
    // first refresh, so "Enviada" may never show: only the end state is checked).
    await expect(page.getByTestId("case-request").filter({ visible: true }).first()).toContainText("Aplicada", { timeout: 30_000 });
    await expect(page.getByText("Este caso ya está decidido.")).toBeVisible();

    // A decision saves at once, but the generation is only cut when an editor recalculates.
    await page.goto("/base");
    await page.getByRole("link", { name: "Hyundai" }).click();
    await expect(page.getByRole("link", { name: "Creta (SUV) (2021+)" })).toHaveCount(0);

    await page.goto("/");
    await expect(page.getByRole("button", { name: "Recalcular ahora" })).toHaveCount(0);
    await page.goto("/usuarios");
    await expect(page.getByRole("main").getByText("Sin acceso")).toBeVisible();
  });
});

test.describe("editor", () => {
  test.use({ as: "editor" });

  test("edita un valor: queda como evidencia manual", async ({ page }) => {
    await page.goto("/base");
    await page.getByRole("link", { name: "Hyundai" }).click();
    await page.getByRole("link", { name: "Creta (SUV)", exact: true }).click();
    const row = page.locator('tr[data-field="length_mm"]');
    await row.getByText("Editar").click();
    await row.getByLabel("Largo").fill("4300");
    await row.getByLabel("Nota").fill("e2e: ficha del fabricante");
    await row.getByRole("button", { name: "Guardar" }).click();
    await expectLatestAction(page, "Aplicada");
    await expect(page.locator('tr[data-field="length_mm"]')).toContainText(/4\.?300 mm/);
    await expect(page.locator('tr[data-field="length_mm"]')).toContainText("Manual");
  });

  test("un valor imposible falla y dice por qué", async ({ page }) => {
    await page.goto("/base");
    await page.getByRole("link", { name: "Hyundai" }).click();
    await page.getByRole("link", { name: "Creta (SUV)", exact: true }).click();
    const row = page.locator('tr[data-field="length_mm"]');
    await row.getByText("Editar").click();
    await row.getByLabel("Largo").fill("no sé");
    await row.getByRole("button", { name: "Guardar" }).click();
    await expectLatestAction(page, "Falló");
    await expect(page.locator('tr[data-field="length_mm"]')).toContainText(/4\.?300 mm/);
  });

  test("corta una generación, recalcula y los anuncios se mueven", async ({ page }) => {
    await page.goto("/base");
    await page.getByRole("link", { name: "Kia" }).click();
    await page.getByRole("link", { name: "Sportage (SUV)", exact: true }).click();
    await expect(page.getByTestId("generation-name").filter({ visible: true })).toContainText("Kia Sportage (SUV)");
    await expect(page.getByTestId("generation-listings").filter({ visible: true })).toHaveText("8 anuncios");
    const split = page.getByTestId("split-form").filter({ visible: true });
    await split.getByLabel("Nueva generación desde el año").fill("2022");
    await split.getByRole("button", { name: "Cortar" }).click();
    await expectLatestAction(page, "Aplicada");
    // Cut now, but its listings only move on the next recalculation.
    await expect(page.getByRole("link", { name: "Sportage (SUV) (2022+)" })).toBeVisible();
    await expect(page.getByTestId("generation-listings").filter({ visible: true })).toHaveText("8 anuncios");

    await page.goto("/");
    const status = page.getByTestId("recalc-status").filter({ visible: true });
    const before = await status.textContent();
    await page.getByRole("button", { name: "Recalcular ahora" }).click();
    // "en cola" / "Recalculando…", then the date of this recalculation and the button again.
    await expect(status).not.toHaveText(before ?? "", { timeout: 60_000 });
    await expect(status).toContainText("cambios aplicados desde el último recálculo", { timeout: 60_000 });
    await expect(page.getByRole("button", { name: "Recalcular ahora" })).toBeVisible();

    await page.goto("/base");
    await page.getByRole("link", { name: "Kia" }).click();
    await page.getByRole("link", { name: "Sportage (SUV)", exact: true }).click();
    await expect(page.getByTestId("generation-listings").filter({ visible: true })).toHaveText("4 anuncios");
    await page.getByRole("link", { name: "Sportage (SUV) (2022+)" }).click();
    await expect(page.getByTestId("generation-name").filter({ visible: true })).toContainText("Sportage (SUV) (2022+)");
    await expect(page.getByTestId("generation-listings").filter({ visible: true })).toHaveText("4 anuncios");

    // The reviewer's approved split of the Creta was applied by the same recalculation.
    await page.goto("/base");
    await page.getByRole("link", { name: "Hyundai" }).click();
    await page.getByRole("link", { name: "Creta (SUV) (2021+)" }).click();
    await expect(page.getByTestId("generation-listings").filter({ visible: true })).toHaveText("4 anuncios");
  });

  test("da acceso a un usuario nuevo", async ({ page }) => {
    await page.goto("/usuarios");
    const form = page.getByTestId("user-form").filter({ visible: true });
    await form.getByLabel("Correo").fill("Nuevo.Revisor@E2E.test");
    await form.getByLabel("Nombre").fill("Nuevo");
    await form.getByLabel("Rol").selectOption("revisor");
    await form.getByRole("button", { name: "Guardar" }).click();
    await expectLatestAction(page, "Aplicada");
    await expect(page.getByRole("row", { name: /nuevo\.revisor@e2e\.test/ })).toContainText("Revisor");
  });
});
