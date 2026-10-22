import { createHmac, randomUUID } from "node:crypto";

import { type Page, expect, test } from "@playwright/test";

import { signup, uniqueEmail } from "./helpers";

interface ApprovalItem {
  id: string;
  title: string;
  status: string;
  resume_run_id: string | null;
}

async function approvalsByTitle(page: Page, title: string): Promise<ApprovalItem[]> {
  const res = await page.request.get("/api/v1/approvals", { params: { status: "all" } });
  expect(res.ok()).toBeTruthy();
  const data = (await res.json()) as { items: ApprovalItem[] };
  return data.items.filter((a) => a.title === title);
}

test("a signed webhook fires a workflow that pauses for approval and completes once approved", async ({ page }) => {
  test.setTimeout(300_000);
  await signup(page, { email: uniqueEmail("flujos"), name: "Fran Flujos", org: "Flujos Norte" });

  // 1. Project
  await page.goto("/app/projects");
  await page.getByRole("button", { name: "Nuevo proyecto" }).first().click();
  const projectDialog = page.getByRole("dialog", { name: "Nuevo proyecto" });
  await projectDialog.getByLabel("Nombre", { exact: true }).fill("Cobros");
  await projectDialog.getByRole("button", { name: "Crear proyecto" }).click();
  await expect(page).toHaveURL(/\/app\/projects\/[0-9a-f-]{36}$/);
  const projectId = new URL(page.url()).pathname.split("/")[3] ?? "";

  // 2. Workflow from the "with approval" starter: input → transform → human approval → output
  await page.getByRole("link", { name: "Flujos", exact: true }).click();
  await expect(page).toHaveURL(/\/workflows$/);
  await page.getByRole("button", { name: "Nuevo flujo" }).first().click();
  const createDialog = page.getByRole("dialog", { name: "Nuevo flujo" });
  await createDialog.getByLabel("Nombre", { exact: true }).fill("facturas");
  await createDialog.getByRole("radio", { name: /Con aprobación/ }).click();
  await createDialog.getByRole("button", { name: "Crear flujo" }).click();
  await expect(page).toHaveURL(/\/workflows\/facturas$/);

  const canvas = page.getByLabel("Lienzo del flujo");
  for (const label of ["Entrada", "Preparar solicitud", "Aprobación", "Resultado"]) {
    await expect(canvas.getByText(label, { exact: true })).toBeVisible();
  }

  // 3. Bind the transform node to the webhook body and save (regenerates workflow.py)
  await canvas.getByText("Preparar solicitud", { exact: true }).click();
  const panel = page.getByRole("complementary", { name: "Configuración del nodo" });
  await expect(panel).toBeVisible();
  await panel.getByLabel("Valor", { exact: true }).fill(
    JSON.stringify({ importe: "{{event.body.importe}}", concepto: "{{event.body.concepto}}", origen: "{{event.type}}" }),
  );
  await expect(page.getByText("Sin guardar").first()).toBeVisible();
  await page.getByRole("button", { name: /^Guardar(\s|$)/ }).click();
  await expect(page.getByText("Flujo guardado y workflow.py regenerado")).toBeVisible();

  // 4. Webhook trigger (development environment): the secret is shown once
  await page.getByRole("tab", { name: "Disparadores" }).click();
  await page.getByRole("button", { name: "Nuevo disparador" }).first().click();
  const triggerDialog = page.getByRole("dialog", { name: "Nuevo disparador" });
  await triggerDialog.getByRole("button", { name: "Crear", exact: true }).click();
  const secretDialog = page.getByRole("dialog", { name: "Webhook creado" });
  await expect(secretDialog).toBeVisible();
  const secret = ((await secretDialog.getByTestId("webhook-secret").textContent()) ?? "").trim();
  expect(secret).toMatch(/^whsec_/);
  await secretDialog.getByRole("button", { name: "Ya lo he guardado" }).click();
  const hookUrl = ((await page.getByTestId("webhook-url").textContent()) ?? "").trim();
  const hookPath = new URL(hookUrl).pathname;
  expect(hookPath).toMatch(/^\/api\/hooks\/[0-9a-f-]{36}$/);

  // 5. Fire it with a signed request (HMAC-SHA256 of "<timestamp>.<body>")
  const body = JSON.stringify({ importe: 830, concepto: "Factura E2E" });
  const unsigned = await page.request.post(hookPath, {
    data: body,
    headers: { "Content-Type": "application/json", "X-Messer-Signature": "t=1,v1=00" },
  });
  expect(unsigned.status()).toBe(401);
  const ts = Math.floor(Date.now() / 1000);
  const signature = createHmac("sha256", secret).update(`${ts}.${body}`).digest("hex");
  const fired = await page.request.post(hookPath, {
    data: body,
    headers: {
      "Content-Type": "application/json",
      "X-Messer-Signature": `t=${ts},v1=${signature}`,
      "X-Messer-Event-Id": `e2e-${randomUUID()}`,
    },
  });
  expect(fired.status()).toBe(202);

  // 6. The run pauses: the approval appears in the inbox
  const title = "¿Aprobar Factura E2E por 830 €?";
  await expect.poll(async () => (await approvalsByTitle(page, title)).length, { timeout: 120_000, intervals: [1_000, 2_000] }).toBe(1);
  await page.goto("/app/approvals");
  const item = page.getByRole("button", { name: new RegExp(title.replace(/[?¿€]/g, ".")) });
  await expect(item).toBeVisible();
  await item.click();
  const sheet = page.getByRole("dialog", { name: title });
  await expect(sheet).toBeVisible();
  await expect(sheet.getByText("Factura E2E").first()).toBeVisible();
  await sheet.getByRole("button", { name: "Aprobar", exact: true }).click();
  await expect(sheet.getByText("Aprobada", { exact: true }).first()).toBeVisible({ timeout: 30_000 });

  // 7. The resumed run completes with the approved values
  let resumeRunId = "";
  await expect
    .poll(
      async () => {
        const [approval] = await approvalsByTitle(page, title);
        resumeRunId = approval?.resume_run_id ?? "";
        if (!resumeRunId) return "waiting";
        const run = await page.request.get(`/api/v1/runs/${resumeRunId}`);
        return run.ok() ? ((await run.json()) as { status: string }).status : "waiting";
      },
      { timeout: 120_000, intervals: [1_000, 2_000] },
    )
    .toBe("success");
  const run = (await (await page.request.get(`/api/v1/runs/${resumeRunId}`)).json()) as { output: unknown };
  expect(run.output).toEqual({ aprobado: true, importe: 830, concepto: "Factura E2E" });

  await page.goto(`/app/projects/${projectId}/traces/${resumeRunId}`);
  await expect(page.getByText("Completada", { exact: true }).first()).toBeVisible();

  // 8. The trigger history shows the firing
  await page.goto(`/app/projects/${projectId}/workflows/facturas`);
  await page.getByRole("tab", { name: "Disparadores" }).click();
  await page.getByRole("button", { name: /Historial \(1\)/ }).click();
  await expect(page.getByText("En pausa", { exact: true }).first()).toBeVisible();
});
