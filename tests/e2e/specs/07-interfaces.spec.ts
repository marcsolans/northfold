import { type APIRequestContext, expect, test } from "@playwright/test";

import { signup, uniqueEmail } from "./helpers";

const INVOICES_CSV = [
  "numero,cliente,importe,estado,fecha_emision,fecha_vencimiento",
  "F-001,Acme,1200.50,pendiente,2026-09-01,2026-10-01",
  "F-002,Globex,300,pendiente,2026-10-05,2026-11-04",
  "F-003,Initech,980,pagada,2026-08-10,2026-09-09",
].join("\n");

async function json<T>(res: Awaited<ReturnType<APIRequestContext["get"]>>): Promise<T> {
  expect(res.ok(), `${res.url()} → ${res.status()} ${await res.text()}`).toBeTruthy();
  return (await res.json()) as T;
}

test("dashboard over a knowledge table previews real rows; the published chat answers a fresh visitor", async ({ page, browser }) => {
  test.setTimeout(240_000);
  await signup(page, { email: uniqueEmail("interfaces"), name: "Irene Interfaces", org: `Interfaces ${Date.now()}` });
  const api = page.request;

  // Project with an agent and a knowledge base holding an invoices table (built through the API).
  const project = await json<{ id: string; slug: string }>(await api.post("/api/v1/projects", { data: { name: "Facturas demo" } }));
  await json(await api.post(`/api/v1/projects/${project.id}/workforce`, { data: { name: "soporte" } }));
  const kb = await json<{ id: string }>(
    await api.post("/api/v1/knowledge-bases", { data: { name: "Facturación", embedding_model: "hash-384", project_id: project.id } }),
  );
  await json(
    await api.post(`/api/v1/knowledge-bases/${kb.id}/tables`, {
      multipart: { files: { name: "facturas.csv", mimeType: "text/csv", buffer: Buffer.from(INVOICES_CSV) } },
    }),
  );

  // Create the dashboard from the UI: KPI + table bound to the knowledge table.
  await page.goto(`/app/projects/${project.id}/interfaces`);
  await expect(page.getByRole("heading", { name: "Interfaces" })).toBeVisible();
  await page.getByRole("button", { name: "Nueva interfaz" }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("radio", { name: /Panel sobre una tabla/ }).click();
  await dialog.getByLabel("Nombre").fill("Panel de facturas");
  await dialog.getByRole("combobox", { name: "Tabla" }).click();
  await page.getByRole("option", { name: /facturas/ }).click();
  await dialog.getByRole("button", { name: "Crear" }).click();

  await expect(page).toHaveURL(new RegExp(`/app/projects/${project.id}/interfaces/[0-9a-f-]+$`));
  await expect(page.getByRole("heading", { name: "Panel de facturas" })).toBeVisible();
  await page.getByRole("tab", { name: "Vista previa" }).click();
  const table = page.getByRole("region", { name: "facturas" });
  await expect(table.getByRole("cell", { name: "F-001" })).toBeVisible();
  await expect(table.getByRole("cell", { name: "Globex" })).toBeVisible();
  await expect(page.getByText("Registros")).toBeVisible();

  // A public chat with the agent, published to production with the Publish button.
  const chat = await json<{ id: string; urls: { public: string } }>(
    await api.post(`/api/v1/projects/${project.id}/interfaces`, {
      data: { template: "public_chat", name: "Asistente de facturas", agent: "soporte" },
    }),
  );
  await page.goto(`/app/projects/${project.id}/interfaces/${chat.id}`);
  await page.getByRole("button", { name: "Publicar" }).click();
  await expect(page.getByRole("button", { name: "Estado de la publicación" })).toHaveText(/Publicado/, { timeout: 150_000 });

  // A fresh browser (no session): anonymous end user.
  const context = await browser.newContext({ locale: "es-ES" });
  const visitor = await context.newPage();
  await visitor.goto(new URL(chat.urls.public).pathname);
  await expect(visitor.getByRole("heading", { name: "Asistente de facturas" })).toBeVisible();
  await visitor.getByLabel("Escribe tu pregunta…").fill("Hola, ¿qué facturas tengo pendientes?");
  await visitor.getByRole("button", { name: "Enviar" }).click();
  const log = visitor.getByRole("log", { name: "Mensajes" });
  await expect(log.getByText("Hola, ¿qué facturas tengo pendientes?")).toBeVisible();
  await expect(log.getByText(/Modo demo/)).toBeVisible({ timeout: 60_000 });

  // Memory per end user: the conversation is still there after a reload (signed cookie).
  await visitor.reload();
  await expect(visitor.getByRole("log", { name: "Mensajes" }).getByText("Hola, ¿qué facturas tengo pendientes?")).toBeVisible();
  await context.close();
});
