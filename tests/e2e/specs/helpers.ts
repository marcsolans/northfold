import { type Page, expect } from "@playwright/test";

export const MAILPIT_URL = process.env.MAILPIT_URL ?? "http://localhost:8025";
export const PASSWORD = "Contrasena123";

export function uniqueEmail(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

interface MailpitSummary {
  ID: string;
  To: { Address: string }[];
  Subject: string;
}

/** Wait for an email to `to` and return its text body (Mailpit API). */
export async function waitForEmail(to: string, subjectIncludes?: string, timeoutMs = 30_000): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const res = await fetch(`${MAILPIT_URL}/api/v1/search?query=${encodeURIComponent(`to:${to}`)}`);
    if (res.ok) {
      const data = (await res.json()) as { messages: MailpitSummary[] };
      const match = data.messages.find((m) => !subjectIncludes || m.Subject.includes(subjectIncludes));
      if (match) {
        const detail = await fetch(`${MAILPIT_URL}/api/v1/message/${match.ID}`);
        const body = (await detail.json()) as { Text: string };
        return body.Text;
      }
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`No email for ${to} (${subjectIncludes ?? "any subject"})`);
}

export function extractLink(text: string, fragment: string): string {
  const match = text.match(new RegExp(`(https?://\\S*${fragment}\\S*)`));
  if (!match?.[1]) throw new Error(`No link containing ${fragment}`);
  return match[1];
}

export async function signup(page: Page, { email, name, org }: { email: string; name: string; org?: string }): Promise<void> {
  await page.goto("/signup");
  await page.getByLabel("Tu nombre").fill(name);
  await page.getByLabel("Email de trabajo").fill(email);
  if (org) await page.getByLabel("Empresa u organización").fill(org);
  await page.getByLabel("Contraseña").fill(PASSWORD);
  await page.getByRole("button", { name: "Crear cuenta" }).click();
  await expect(page).toHaveURL(/\/(onboarding|app)/);
}
