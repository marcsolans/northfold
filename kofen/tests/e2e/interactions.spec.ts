import { expect, test } from "@playwright/test";

test.describe("live console", () => {
  test("autoplays only on screen, switches scenarios, approves, pauses", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/en", { waitUntil: "networkidle" });
    const frame = page.locator(".console-frame");
    const clock = page.locator("#try span[dir=ltr][aria-hidden=true]").last();

    // Off-screen at load: paused.
    await expect(frame).toHaveAttribute("data-paused", "");
    await page.locator("#try").scrollIntoViewIfNeeded();
    await expect(frame).not.toHaveAttribute("data-paused", "");
    await page.waitForTimeout(2200);
    expect(await clock.textContent()).toMatch(/^0:0[1-3] \/ 0:39$/);

    // Steps appear with the timeline.
    await expect(page.locator("#try").getByText("Read all 184 pages and both annexes").last()).toBeVisible();

    await page.getByRole("button", { name: "Margin audit", exact: true }).click();
    await expect(page.getByRole("button", { name: "Margin audit", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator("#try > div").first()).toContainText("Margin audit");

    // Approve jumps to the done state once the card is shown.
    const approve = page.locator("#try").getByRole("button", { name: "Approve", exact: true });
    await approve.waitFor({ timeout: 15_000 });
    await approve.click();
    await expect(page.locator("#try").getByRole("button", { name: "✓ Approve" })).toBeDisabled();

    await page.getByRole("button", { name: "Pause demo" }).click();
    const t1 = await clock.textContent();
    await page.waitForTimeout(1500);
    expect(await clock.textContent()).toBe(t1);
  });

  test("composer chips and Enter build the proposal mailto", async ({ page }) => {
    await page.goto("/en");
    await page.locator("#try").scrollIntoViewIfNeeded();
    await page.getByRole("button", { name: "Tenders", exact: true }).nth(1).click();
    await expect(page.locator("#console-q")).toHaveValue("We bid on public and private tenders.");
    await expect(page.getByRole("button", { name: "Tenders", exact: true }).nth(1)).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator("#try a.btn")).toHaveAttribute("href", /subject=Proposal%20request&body=We%20bid/);
  });
});

test.describe("industries rail", () => {
  for (const locale of ["en", "ar"]) {
    test(`next / dots / prev (${locale})`, async ({ page }) => {
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto(`/${locale}`);
      const section = page.locator("#industries");
      await section.scrollIntoViewIfNeeded();
      const buttons = section.locator("button[aria-label]");
      const prev = buttons.first();
      const next = buttons.last();
      const left = () => section.locator(".rail").evaluate((el) => Math.abs(el.scrollLeft));

      await expect(prev).toBeDisabled();
      await next.click();
      await expect.poll(left).toBeGreaterThan(300);
      await expect(prev).toBeEnabled();
      await section.locator(".h-11 button").last().click();
      await expect(next).toBeDisabled();
      await prev.click();
      await expect(next).toBeEnabled();
    });
  }
});

test.describe("phases", () => {
  test("autoplay advances, click stops it", async ({ page }) => {
    await page.goto("/en");
    await page.locator("#phases").scrollIntoViewIfNeeded();
    await expect(page.locator("#phases [role=tab][aria-selected=true]")).toHaveText(/02/, { timeout: 9000 });
    await page.locator("#phases [role=tab]").first().click();
    await page.waitForTimeout(7000);
    await expect(page.locator("#phases [role=tab][aria-selected=true]")).toHaveText(/01/);
  });
});

test.describe("navigation", () => {
  test("language listbox: opens, closes on Escape and outside click, switches locale", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/en");
    const trigger = page.locator("header button[aria-haspopup=listbox]");
    await trigger.click();
    await expect(page.getByRole("listbox")).toBeVisible();
    await expect(page.getByRole("option", { selected: true })).toContainText("English");
    await page.keyboard.press("Escape");
    await expect(page.getByRole("listbox")).toHaveCount(0);
    await trigger.click();
    await page.mouse.click(700, 600);
    await expect(page.getByRole("listbox")).toHaveCount(0);
    await trigger.click();
    await page.getByRole("option", { name: /Español/ }).click();
    await expect(page).toHaveURL(/\/es$/);
    await expect(page.locator("html")).toHaveAttribute("lang", "es");
  });

  test("mobile menu opens and closes", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/en");
    const burger = page.getByRole("button", { name: "Open menu" });
    await burger.click();
    await expect(page.getByRole("button", { name: "Close menu" })).toHaveAttribute("aria-expanded", "true");
    await page.locator("nav ul a").first().click();
    await expect(page.getByRole("button", { name: "Open menu" })).toHaveAttribute("aria-expanded", "false");
  });

  test("FAQ items open independently", async ({ page }) => {
    await page.goto("/en");
    const q = page.locator("#faq button[aria-expanded]");
    await q.nth(0).click();
    await q.nth(2).click();
    await expect(q.nth(0)).toHaveAttribute("aria-expanded", "true");
    await expect(q.nth(2)).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByText("It rarely is.")).toBeVisible();
  });
});

test.describe("lead form", () => {
  test("validates client-side and falls back to mailto without a mail provider", async ({ page }) => {
    await page.goto("/en");
    const form = page.locator("#top form");
    await form.getByRole("button").click();
    await expect(page.locator("#top [role=status]")).toHaveText("Enter your work email.");
    await form.locator("input[type=email]").fill("not-an-email");
    await form.getByRole("button").click();
    await expect(page.locator("#top [role=status]")).toHaveText("That email doesn’t look right.");

    // With RESEND_API_KEY unset the API answers { fallback: "mailto" }.
    const response = page.waitForResponse("**/api/lead");
    await form.locator("input[type=email]").fill("ops@example.com");
    await form.getByRole("button").click();
    const res = await response;
    if (res.status() === 503) {
      expect(await res.json()).toMatchObject({ fallback: "mailto" });
      await expect(page.locator("#top [role=status]")).toHaveText("Opening your email app…");
    } else {
      expect(res.status()).toBe(200);
    }
  });
});

test.describe("reduced motion and no JS", () => {
  test("reduced motion: counters final, rotator still, console at rest", async ({ browser }) => {
    const ctx = await browser.newContext({ reducedMotion: "reduce", viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    await page.goto("/en", { waitUntil: "networkidle" });
    await page.waitForTimeout(3000);
    await expect(page.locator(".rotator span").first()).toHaveCSS("opacity", "1");
    await page.locator("#platform").scrollIntoViewIfNeeded();
    await expect(page.locator("#platform dd").last()).toContainText("100");
    await page.locator("#try").scrollIntoViewIfNeeded();
    await expect(page.getByRole("button", { name: "Play demo" })).toBeVisible();
    await ctx.close();
  });

  test("without JS every section's content is visible", async ({ browser }) => {
    const ctx = await browser.newContext({ javaScriptEnabled: false });
    const page = await ctx.newPage();
    await page.goto("/en");
    for (const text of ["Agents that move the P&L.", "From €60,000", "It rarely is.", "Public sector & Government"]) {
      await expect(page.getByText(text).first()).toBeVisible();
    }
    // The live console view comes after its invisible sizing copies.
    await expect(page.locator("#try").getByText("Estimated score 82/100").last()).toBeVisible();
    await ctx.close();
  });
});
