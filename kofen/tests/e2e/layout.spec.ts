import { expect, test } from "@playwright/test";
import { horizontalOverflow, scrollThrough } from "./helpers";

const LOCALES = ["en", "es", "ar"] as const;
const WIDTHS = [390, 768, 1024, 1440] as const;

for (const locale of LOCALES) {
  for (const width of WIDTHS) {
    test(`${locale} @ ${width}px: renders, no horizontal scroll, screenshot`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(`/${locale}`, { waitUntil: "networkidle" });

      await expect(page.locator("html")).toHaveAttribute("lang", locale);
      await expect(page.locator("html")).toHaveAttribute("dir", locale === "ar" ? "rtl" : "ltr");
      for (const id of ["top", "try", "deployment", "phases", "platform", "industries", "pricing", "faq", "company", "contact"]) {
        await expect(page.locator(`#${id}`)).toHaveCount(1);
      }

      await scrollThrough(page);
      expect(await horizontalOverflow(page)).toBeLessThanOrEqual(0);

      // Everything revealed after scrolling (nothing stuck hidden).
      expect(await page.locator('[data-reveal="pending"]').count()).toBe(0);

      await page.evaluate(() => window.scrollTo(0, 0));
      await page.waitForTimeout(300);
      await page.screenshot({ path: `artifacts/screenshots/${locale}-${width}.png`, fullPage: true });
    });
  }
}

test("root redirects by Accept-Language, falling back to en", async ({ browser }) => {
  for (const [browserLocale, expected] of [["es-ES", "/es"], ["ar-EG", "/ar"], ["ja-JP", "/en"]] as const) {
    // The context locale drives the Accept-Language header Chromium sends.
    const ctx = await browser.newContext({ locale: browserLocale });
    const page = await ctx.newPage();
    await page.goto("/");
    expect(new URL(page.url()).pathname).toBe(expected);
    await ctx.close();
  }
});

test("sticky header stays on top while scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/en");
  await page.evaluate(() => window.scrollTo(0, 3000));
  await page.waitForTimeout(200);
  const box = await page.locator("header").boundingBox();
  expect(box?.y).toBe(0);
});
