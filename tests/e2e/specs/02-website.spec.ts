import { type Page, expect, test } from "@playwright/test";

import { PASSWORD, uniqueEmail } from "./helpers";

const PLANS: [name: string, price: RegExp][] = [
  ["Starter", /49\s€/],
  ["Pro", /199\s€/],
  ["Business", /799\s€/],
  ["Enterprise", /3000\s€/],
];

async function dismissCookieBanner(page: Page): Promise<void> {
  const reject = page.getByRole("button", { name: "Solo imprescindibles" });
  if (await reject.isVisible().catch(() => false)) await reject.click();
}

test("landing → pricing shows the four plans with prices → sign up from a plan CTA lands on onboarding", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { level: 1, name: "Describe tu problema. Messer construye la solución y la pone en producción." }),
  ).toBeVisible();
  // The Composer animation is plain HTML/CSS (no video) and describes itself to assistive technology.
  await expect(page.getByRole("img", { name: /Animación del Composer/ })).toBeVisible();
  await dismissCookieBanner(page);

  await page.getByRole("navigation", { name: "Navegación principal" }).getByRole("link", { name: "Precios" }).click();
  await expect(page).toHaveURL(/\/pricing$/);
  await expect(page.getByRole("heading", { level: 1, name: "Precios claros para llevar la IA a producción" })).toBeVisible();

  for (const [name, price] of PLANS) {
    const card = page.getByRole("article", { name, exact: true });
    await expect(card).toBeVisible();
    await expect(card.getByText(price).first()).toBeVisible();
  }
  await expect(page.getByRole("article", { name: "Enterprise", exact: true }).getByText("Desde").first()).toBeVisible();

  // Annual billing shows the yearly price without reloading.
  await page.locator("label[for=billing-annual]").click();
  await expect(page.getByRole("article", { name: "Pro", exact: true }).getByText(/1990\s€/)).toBeVisible();
  await page.locator("label[for=billing-monthly]").click();

  await page.getByRole("article", { name: "Pro", exact: true }).getByRole("link", { name: "Prueba 14 días gratis" }).click();
  await expect(page).toHaveURL(/\/signup\?plan=pro$/);

  const email = uniqueEmail("website");
  await page.getByLabel("Tu nombre").fill("Wanda Web");
  await page.getByLabel("Email de trabajo").fill(email);
  await page.getByLabel("Empresa u organización").fill("Clínica Norte");
  await page.getByLabel("Contraseña").fill(PASSWORD);
  await page.getByRole("button", { name: "Crear cuenta" }).click();

  await expect(page).toHaveURL(/\/onboarding(\?|$)/);
  await expect(page.getByRole("heading", { level: 1, name: "Pon en marcha tu primer agente" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "¿Qué quieres resolver?" })).toBeVisible();

  // Step 1 is stored in the organization and marks the step as done.
  await page.getByLabel("Tu caso").fill("Responder a los clientes sobre sus facturas con nuestras condiciones.");
  await page.getByRole("button", { name: "Guardar y continuar" }).click();
  await expect(page.getByRole("heading", { name: "Elige una plantilla o describe tu caso al Composer" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Abrir el Composer" })).toHaveAttribute("href", /\/app\?prompt=Responder/);
  await expect(page.getByText("1 de 4 completados")).toBeVisible();
});

test("public website pages, legal drafts and the contact form", async ({ page }) => {
  await page.goto("/security");
  await expect(page.getByRole("heading", { level: 1, name: "Seguridad, privacidad y cumplimiento" })).toBeVisible();
  await dismissCookieBanner(page);

  await page.goto("/legal/dpa");
  await expect(page.getByText("Borrador — pendiente de revisión por un abogado")).toBeVisible();
  await expect(page.getByRole("heading", { level: 1, name: "Acuerdo de tratamiento de datos (DPA)" })).toBeVisible();

  await page.goto("/docs/concepts");
  await expect(page.getByRole("heading", { level: 1, name: "Conceptos" })).toBeVisible();
  await expect(page.getByRole("table").first()).toBeVisible();

  await page.goto("/blog");
  await page.getByRole("link", { name: "Aprobación humana en agentes: dónde ponerla y cómo diseñarla" }).click();
  await expect(page.getByRole("heading", { level: 1, name: /Aprobación humana en agentes/ })).toBeVisible();

  const rss = await page.request.get("/blog/rss.xml");
  expect(rss.ok()).toBe(true);
  expect(await rss.text()).toContain("<rss");

  await page.goto("/status");
  await expect(page.getByRole("heading", { level: 1, name: "Estado del servicio" })).toBeVisible();

  await page.goto("/contact?topic=enterprise");
  await expect(page.getByLabel("Tema")).toHaveValue("enterprise");
  await page.getByRole("button", { name: "Enviar mensaje" }).click();
  await expect(page.getByText("Revisa los campos marcados.")).toBeVisible();
  await page.getByLabel("Nombre").fill("Lucía Ferrer");
  await page.getByLabel("Email de trabajo").fill(uniqueEmail("lead"));
  await page.getByLabel(/Empresa/).fill("Clínica Norte");
  await page.getByLabel("¿En qué podemos ayudarte?").fill("Queremos residencia UE estricta para 40 personas.");
  await page.getByRole("button", { name: "Enviar mensaje" }).click();
  await expect(page.getByText("Mensaje enviado")).toBeVisible();
});
