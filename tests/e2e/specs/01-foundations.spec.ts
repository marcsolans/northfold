import { expect, test } from "@playwright/test";

import { PASSWORD, extractLink, signup, uniqueEmail, waitForEmail } from "./helpers";

test("sign up, create an organization and invite a viewer", async ({ page, browser }) => {
  const owner = uniqueEmail("owner");
  await signup(page, { email: owner, name: "Olga Owner", org: "Facturación Norte" });

  await page.goto("/app/settings/members");
  await expect(page.getByRole("heading", { name: "Miembros y roles" })).toBeVisible();
  await expect(page.getByText(owner)).toBeVisible();

  const viewer = uniqueEmail("viewer");
  await page.getByRole("button", { name: "Invitar" }).click();
  await page.getByLabel("Email").fill(viewer);
  await page.getByRole("dialog").getByRole("button", { name: "Invitar" }).click();
  await expect(page.getByText(`Invitación enviada a ${viewer}`)).toBeVisible();

  const email = await waitForEmail(viewer, "te invita");
  const inviteUrl = extractLink(email, "/invite/");

  const context = await browser.newContext();
  const guest = await context.newPage();
  await guest.goto(inviteUrl);
  await expect(guest.getByText("Facturación Norte")).toBeVisible();
  await guest.getByRole("link", { name: "Crear cuenta y unirme" }).click();
  await guest.getByLabel("Tu nombre").fill("Víctor Viewer");
  await guest.getByLabel("Email de trabajo").fill(viewer);
  await guest.getByLabel("Contraseña").fill(PASSWORD);
  await guest.getByRole("button", { name: "Crear cuenta" }).click();
  await expect(guest).toHaveURL(/\/(onboarding|app)/);

  await guest.goto("/app/settings/members");
  await expect(guest.getByText(owner)).toBeVisible();
  // A viewer has no invite button.
  await expect(guest.getByRole("button", { name: "Invitar" })).toHaveCount(0);
  await context.close();

  await page.reload();
  await expect(page.getByText(viewer)).toBeVisible();
});
