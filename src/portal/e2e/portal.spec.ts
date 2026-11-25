import { generateKeyPairSync } from "node:crypto";
import { readFileSync } from "node:fs";

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

test.describe("fichas (después del recálculo)", () => {
  test.use({ as: "lector" });

  test("lista los vehículos y abre la ficha de identidad de uno", async ({ page }) => {
    await page.goto("/fichas");
    const total = page.getByTestId("identity-total").filter({ visible: true });
    // one sheet per live variant: two Cretas (1.6 and 1.5) and two Sportages; the Zoe's model
    // wasn't accepted, so it has none
    await expect(total).toHaveText("4 fichas");
    await page.getByPlaceholder("Buscar marca, modelo, versión…").fill("hyundai creta");
    await page.getByRole("button", { name: "Filtrar" }).click();
    await expect(total).toHaveText("2 fichas");
    await page.getByTestId("identity-row").filter({ visible: true, hasText: "121 hp" }).getByRole("link").click();

    // Only the base's values, with where each came from: the editor's manual length (published
    // on the generation by the recalculation) and the power the listings agree on.
    await expect(page.getByTestId("identity-name").filter({ visible: true })).toHaveText("Hyundai Creta Advance");
    await expect(page.locator('[data-field="length_mm"]').filter({ visible: true })).toHaveText(/4\.?300 mm/);
    await expect(page.locator('[data-source="length_mm"]').filter({ visible: true })).toHaveText("Manual");
    await expect(page.locator('[data-field="horsepower_hp"]').filter({ visible: true })).toHaveText("121 hp");
    await expect(page.locator('[data-source="horsepower_hp"]').filter({ visible: true })).toHaveText("Anuncios");

    // its listings open their final record, which leads back to the vehicle
    await expect(page.getByTestId("identity-listing").filter({ visible: true })).toHaveCount(4);
    await page.getByTestId("identity-listing").filter({ visible: true }).first().getByRole("link", { name: "2017" }).click();
    await expect(page.getByTestId("final-name").filter({ visible: true })).toHaveText("Hyundai Creta Advance 2017");
    await expect(page.getByTestId("final-status").filter({ visible: true })).toHaveText("Asignado");
    await page.getByRole("link", { name: "Ficha del vehículo", exact: true }).click();
    await expect(page.getByTestId("identity-name").filter({ visible: true })).toHaveText("Hyundai Creta Advance");
    await page.getByRole("main").getByRole("link", { name: "Fichas", exact: true }).filter({ visible: true }).click();
    await expect(total).toHaveText("4 fichas");
  });

  test("un lector no entra a Captura", async ({ page }) => {
    await page.goto("/captura");
    await expect(page.getByRole("main").getByText("Sin acceso")).toBeVisible();
    await expect(page.getByTestId("export-form")).toHaveCount(0);
  });
});

test.describe("captura (revisor)", () => {
  test.use({ as: "revisor" });

  test("prepara la plantilla, la descarga y la sube", async ({ page }) => {
    await page.goto("/captura");
    const form = page.getByTestId("export-form").filter({ visible: true });
    await form.getByLabel("Marca").fill("Kia");
    await form.getByRole("button", { name: "Preparar plantilla" }).click();
    // the worker writes it with kb/specs.py; the page refreshes until the link shows
    const link = page.getByTestId("templates").getByRole("link", { name: "Descargar" }).first();
    await expect(link).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("templates")).toContainText("Kia");
    const [download] = await Promise.all([page.waitForEvent("download"), link.click()]);
    expect(download.suggestedFilename()).toBe("plantilla-captura-Kia.xlsx");
    // Playwright keeps it under a temporary name without the extension: upload it by its name
    const file = {
      name: download.suggestedFilename(),
      mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      buffer: readFileSync(await download.path()),
    };

    // the portal refuses what isn't a template before queueing anything
    const upload = page.getByTestId("upload-form").filter({ visible: true });
    await upload.getByLabel("Plantilla llena (.xlsx)").setInputFiles({
      name: "notas.txt", mimeType: "text/plain", buffer: Buffer.from("hola"),
    });
    await upload.getByRole("button", { name: "Subir" }).click();
    await expect(upload).toContainText("El archivo debe ser .xlsx");

    // the template as downloaded (nothing filled) saves nothing and reports no errors
    await upload.getByLabel("Plantilla llena (.xlsx)").setInputFiles(file);
    await upload.getByRole("button", { name: "Subir" }).click();
    const result = page.getByTestId("upload").filter({ visible: true }).first();
    await expect(result).toContainText("Aplicada", { timeout: 30_000 });
    await expect(result.getByTestId("upload-saved")).toHaveText("Nada nuevo.");
  });
});
