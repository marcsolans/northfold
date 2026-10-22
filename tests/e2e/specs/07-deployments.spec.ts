import { type Page, expect, test } from "@playwright/test";

import { signup, uniqueEmail } from "./helpers";

async function publishToProduction(page: Page, message?: string): Promise<void> {
  await page.getByRole("button", { name: "Publicar", exact: true }).first().click();
  const dialog = page.getByRole("dialog", { name: "Publicar" });
  await expect(dialog.getByRole("radio", { name: /Producción/ })).toBeChecked();
  // The owner is an admin: the forced-deploy option is offered, unchecked.
  await expect(dialog.getByRole("checkbox", { name: "Forzar aunque fallen las evals" })).not.toBeChecked();
  if (message) await dialog.getByLabel("Mensaje de la versión").fill(message);
  await dialog.getByRole("button", { name: "Publicar en Producción" }).click();
  await expect(dialog).toBeHidden();
}

test("publish to production, watch it go live, roll back, add a secret and manage an API key", async ({ page }) => {
  test.setTimeout(300_000);
  await signup(page, { email: uniqueEmail("deploy"), name: "Dani Despliegue", org: "Pedidos Despliegue" });

  // 1. Project + agent
  await page.goto("/app/projects");
  await page.getByRole("button", { name: "Nuevo proyecto" }).first().click();
  const projectDialog = page.getByRole("dialog", { name: "Nuevo proyecto" });
  await projectDialog.getByLabel("Nombre", { exact: true }).fill("Pedidos online");
  await projectDialog.getByRole("button", { name: "Crear proyecto" }).click();
  await expect(page).toHaveURL(/\/app\/projects\/[0-9a-f-]{36}$/);
  const projectUrl = page.url();

  await page.getByRole("link", { name: "Agentes", exact: true }).click();
  await page.getByRole("button", { name: "Nuevo agente" }).first().click();
  const agentDialog = page.getByRole("dialog", { name: "Nuevo agente" });
  await agentDialog.getByLabel("Nombre", { exact: true }).fill("pedidos");
  await agentDialog.getByRole("button", { name: "Crear agente" }).click();
  await expect(page).toHaveURL(/\/agents\/pedidos$/);

  // 2. Deployments tab: nothing published yet
  await page.goto(projectUrl);
  await page.getByRole("link", { name: "Despliegues", exact: true }).click();
  await expect(page).toHaveURL(/\/deployments$/);
  await expect(page.getByRole("heading", { level: 1, name: "Despliegues" })).toBeVisible();
  await expect(page.getByText("Aún no has publicado")).toBeVisible();

  // 3. Publish the latest code to production and watch the pipeline until it is live
  await publishToProduction(page, "Primera versión");
  const progress = page.getByRole("region", { name: "Progreso del despliegue en Producción" }).first();
  await expect(progress).toBeVisible();
  await expect(progress.getByRole("list", { name: "Fases del despliegue" })).toBeVisible();
  await expect(page.getByText("Publicado en Producción: versión 1")).toBeVisible({ timeout: 120_000 });
  await expect(progress.getByText("pedidos", { exact: true })).toBeVisible();
  await expect(progress.getByText("Sin evals")).toBeVisible();
  await expect(progress.getByRole("log", { name: "Registro" })).toContainText("Publicado en production");

  const history = page.getByRole("table", { name: "Historial" });
  await expect(history.getByRole("row").nth(1)).toContainText("v1");
  await expect(history.getByRole("row").nth(1)).toContainText("Publicado");

  // 4. A second version, then roll back to the first one
  await publishToProduction(page, "Segunda versión");
  await expect(page.getByText("Publicado en Producción: versión 2")).toBeVisible({ timeout: 120_000 });
  await expect(history.getByRole("row").nth(1)).toContainText("v2");
  const firstRow = history.getByRole("row").filter({ hasText: "Primera versión" });
  await expect(firstRow).toContainText("Sustituido");
  await firstRow.getByRole("button", { name: "Volver a esta versión" }).click();
  const confirm = page.getByRole("alertdialog", { name: "¿Volver a la versión 1 en Producción?" });
  await confirm.getByRole("button", { name: "Volver a esta versión" }).click();
  await expect(confirm).toBeHidden();
  const rollback = page.getByRole("region", { name: "Progreso del despliegue en Producción" }).first();
  await expect(rollback.getByText("Evals omitidas").first()).toBeVisible();
  await expect(history.getByRole("row").nth(1)).toContainText("v1", { timeout: 120_000 });
  await expect(history.getByRole("row").nth(1)).toContainText("Publicado", { timeout: 120_000 });

  // 5. Project secret: name rules, then a value that is never shown back
  await page.goto(`${projectUrl}/settings`);
  await expect(page.getByRole("heading", { name: "Secretos", exact: true })).toBeVisible();
  const secretForm = page.locator("form").filter({ hasText: "Añadir o reemplazar un secreto" });
  const secretName = secretForm.getByLabel("Nombre", { exact: true });
  await secretName.fill("crm token");
  await secretName.blur();
  await expect(secretForm.getByText(/Usa solo MAYÚSCULAS/)).toBeVisible();
  await secretName.fill("MESSER_TOKEN");
  await expect(secretForm.getByText("Los prefijos MESSER_, ANTHROPIC_ y AWS_ están reservados por la plataforma.")).toBeVisible();
  await secretName.fill("CRM_TOKEN");
  await secretForm.getByLabel("Valor", { exact: true }).fill("valor-muy-secreto-123");
  await secretForm.getByRole("button", { name: "Añadir secreto" }).click();
  await expect(page.getByText("Secreto CRM_TOKEN añadido")).toBeVisible();
  await expect(page.getByRole("list", { name: "Secretos del proyecto" }).getByText("CRM_TOKEN", { exact: true })).toBeVisible();
  await expect(page.getByText("valor-muy-secreto-123")).toHaveCount(0);

  // 6. API key: create with a scope, copy-once panel, then revoke
  await page.goto("/app/settings/api-keys");
  await expect(page.getByRole("heading", { level: 1, name: "API keys" })).toBeVisible();
  await page.getByRole("button", { name: "Crear API key" }).first().click();
  const keyDialog = page.getByRole("dialog", { name: "Crear API key" });
  await keyDialog.getByLabel("Nombre", { exact: true }).fill("Integración CRM");
  await keyDialog.getByRole("checkbox", { name: /runs:write/ }).click();
  await keyDialog.getByRole("button", { name: "Crear API key" }).click();
  const created = page.getByRole("dialog", { name: "API key creada" });
  await expect(created.getByText("Cópiala ahora")).toBeVisible();
  await expect(created.getByLabel("Clave de «Integración CRM»")).toHaveValue(/^msr_/);
  await created.getByRole("button", { name: "Ya la he guardado" }).click();
  await expect(created).toBeHidden();

  const keyRow = page.getByRole("table", { name: "API keys de la organización" }).getByRole("row").filter({ hasText: "Integración CRM" });
  await expect(keyRow).toContainText("runs:write");
  await expect(keyRow).toContainText("Activa");
  await keyRow.getByRole("button", { name: "Revocar la API key Integración CRM" }).click();
  const revokeDialog = page.getByRole("alertdialog", { name: "¿Revocar la API key «Integración CRM»?" });
  await revokeDialog.getByRole("button", { name: "Revocar", exact: true }).click();
  await expect(page.getByText("API key «Integración CRM» revocada")).toBeVisible();
  await expect(keyRow).toContainText("Revocada el");
  await expect(keyRow.getByRole("button", { name: /Revocar/ })).toHaveCount(0);
});
