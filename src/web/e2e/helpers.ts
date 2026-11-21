import { expect, type Page } from "@playwright/test";

/** Every test acts as the same reviewer (the name is kept in a cookie). */
export async function signIn(page: Page) {
  await page.goto("/cola");
  const name = page.getByLabel("Tu nombre");
  // the reviewer box streams in: wait for one of its two states (isVisible() does not wait)
  await expect(name.or(page.getByText("Revisando como"))).toBeVisible();
  if (await name.isVisible()) {
    await name.fill("E2E Revisor");
    await page.getByRole("button", { name: "Guardar" }).click();
  }
  await expect(page.getByText("Revisando como")).toContainText("E2E Revisor");
}
