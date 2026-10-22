import { expect, test } from "@playwright/test";

import { signup, uniqueEmail } from "./helpers";

const PROMPT = 'Envía un email a ana@example.com con asunto "Factura 1043" y el texto "Su factura ya está pagada"';

test("build an agent in Studio, approve a gated tool from the playground and inspect the trace", async ({ page }) => {
  test.setTimeout(240_000);
  await signup(page, { email: uniqueEmail("studio"), name: "Sara Studio", org: "Facturas Studio" });

  // 1. Project
  await page.goto("/app/projects");
  await expect(page.getByRole("heading", { name: "Proyectos", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Nuevo proyecto" }).first().click();
  const projectDialog = page.getByRole("dialog", { name: "Nuevo proyecto" });
  await projectDialog.getByLabel("Nombre", { exact: true }).fill("Atención de facturas");
  await projectDialog.getByLabel("Descripción", { exact: true }).fill("Dudas de facturas y avisos a clientes");
  await projectDialog.getByRole("button", { name: "Crear proyecto" }).click();
  await expect(page).toHaveURL(/\/app\/projects\/[0-9a-f-]{36}$/);

  // 2. Agent (the name is validated inline)
  await page.getByRole("link", { name: "Agentes", exact: true }).click();
  await expect(page).toHaveURL(/\/agents$/);
  await page.getByRole("button", { name: "Nuevo agente" }).first().click();
  const agentDialog = page.getByRole("dialog", { name: "Nuevo agente" });
  const nameInput = agentDialog.getByLabel("Nombre", { exact: true });
  await nameInput.fill("1soporte");
  await expect(agentDialog.getByText("El nombre debe empezar por una letra minúscula.")).toBeVisible();
  await nameInput.fill("soporte");
  await agentDialog.getByRole("button", { name: "Crear agente" }).click();
  await expect(page).toHaveURL(/\/agents\/soporte$/);

  // 3. Tool "Enviar email" with approval, then save the configuration
  await expect(page.getByRole("heading", { name: "Herramientas", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Añadir herramienta" }).click();
  const picker = page.getByRole("dialog", { name: "Añadir herramienta" });
  await picker.getByRole("button", { name: /Enviar email/ }).click();
  await expect(picker).toBeHidden();
  const emailTool = page.getByRole("listitem").filter({ hasText: "send_email" });
  const approvalSwitch = emailTool.getByRole("switch", { name: /Requiere aprobación/ });
  await expect(approvalSwitch).toBeChecked();
  await expect(approvalSwitch).toBeDisabled();
  await expect(page.getByText("Cambios sin guardar").first()).toBeVisible();
  await page.getByRole("button", { name: /^Guardar(\s|$)/ }).click();
  await expect(page.getByText("Configuración guardada")).toBeVisible();

  // 4. Chat: the gated tool pauses the run and shows the inline approval card
  const message = page.getByLabel("Mensaje", { exact: true });
  await message.fill(PROMPT);
  await message.press("Enter");
  const card = page.getByRole("region", { name: "Aprobación requerida para send_email" });
  await expect(card).toBeVisible({ timeout: 90_000 });
  await expect(card.getByText("ana@example.com")).toBeVisible();
  await expect(page.getByText("En pausa", { exact: true })).toBeVisible({ timeout: 30_000 });

  // 5. Approve: the resumed run streams into the same thread and succeeds
  await card.getByRole("button", { name: "Aprobar", exact: true }).click();
  await expect(card.getByText("Aprobada", { exact: true })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("Continuación tras la decisión")).toBeVisible();
  await expect(page.getByText("Completada", { exact: true })).toBeVisible({ timeout: 90_000 });

  // 6. Trace of the resumed run: spans, cost and credits
  await page.getByRole("link", { name: "Ver traza" }).last().click();
  await expect(page).toHaveURL(/\/traces\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { level: 1, name: /soporte/ })).toBeVisible();
  const tree = page.getByRole("tree", { name: "Árbol de pasos" });
  await expect(tree.getByRole("treeitem").first()).toBeVisible();
  await expect(tree.getByText("send_email", { exact: true }).first()).toBeVisible();
  await expect(tree.getByText("Modelo", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Coste", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/US\$/).first()).toBeVisible();
  await expect(page.getByText("Créditos descontados")).toBeVisible();
  await expect(page.getByText("Aprobaciones de la ejecución")).toBeVisible();
});
