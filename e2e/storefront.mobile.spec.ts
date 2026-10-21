import { expect, test } from "@playwright/test";

import { addToBag, summaryValue } from "./support/shop";

test("shop from a phone: menu, filter sheet and bag", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Open menu" }).click();
  const menu = page.getByRole("dialog", { name: "Menu" });
  await menu.getByRole("link", { name: "Men", exact: true }).click();
  await expect(page).toHaveURL("/shop?category=men");
  await expect(menu).toBeHidden();

  await page.getByRole("button", { name: /Filters/ }).click();
  const sheet = page.getByRole("dialog", { name: "Filters" });
  await sheet.getByRole("checkbox", { name: "Shoes" }).check();
  await expect(page).toHaveURL("/shop?category=men&type=shoes");
  await page.keyboard.press("Escape");
  await expect(sheet).toBeHidden();
  const results = page.getByRole("region", { name: "Products" });
  await expect(
    results.getByRole("link", { name: "Minimal Leather Sneakers" }).first(),
  ).toBeVisible();

  await addToBag(page, "minimal-leather-sneakers", "M");
  await page.goto("/cart");
  // $165 is over the free-shipping threshold.
  await expect(summaryValue(page, "Shipping")).toHaveText("Free");
  await expect(summaryValue(page, "Total")).toHaveText("$165.00");
});
