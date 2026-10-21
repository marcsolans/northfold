import { expect, test } from "@playwright/test";

import { STORAGE_STATE } from "./support/accounts";
import { addToBag, checkoutCashOnDelivery, POPLIN_SHIRT } from "./support/shop";

test.use({ storageState: STORAGE_STATE.admin });

test("an admin creates a product that appears in the shop, then archives it", async ({ page }) => {
  const name = `Alpine Merino Scarf ${Date.now()}`;
  await page.goto("/admin/products/new");
  await page.getByLabel("Name", { exact: true }).fill(name);
  await page.getByLabel("Description").fill("A ribbed scarf in fine Alpine merino wool.");
  await page.getByLabel("Price (USD)").fill("45.00");
  await page.getByLabel("Category").selectOption("WOMEN");
  await page.getByLabel("Product type").selectOption("JACKET");
  await page
    .getByLabel("Image URL")
    .fill("https://images.unsplash.com/photo-1434389677669-e08b4cac3105");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByLabel("Colour of variant 1").fill("Oat");
  await page.getByRole("button", { name: "Auto" }).first().click();
  await page.getByLabel("Stock of variant 1").fill("5");
  await page.getByRole("button", { name: "Create product" }).click();
  await expect(page).toHaveURL(/\/admin\/products\/[^/]+\/edit$/);
  const slug = await page.getByLabel("URL slug").filter({ visible: true }).inputValue();

  // Live in the store: product page and search.
  await page.goto(`/products/${slug}`);
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
  await expect(page.getByText("$45.00").first()).toBeVisible();
  await page.goto(`/shop?q=${encodeURIComponent(name)}`);
  await expect(page.getByRole("region", { name: "Products" }).getByText(name)).toBeVisible();

  // Archived products disappear from the store but stay in the admin.
  await page.goto("/admin/products");
  await page.getByRole("link", { name }).click();
  await page.getByLabel("Archived").filter({ visible: true }).check();
  await page.getByRole("button", { name: "Save changes" }).filter({ visible: true }).click();
  await expect(page.getByText("Product saved")).toBeVisible();
  await page.goto(`/products/${slug}`);
  await expect(page.getByRole("heading", { name: "We couldn’t find that page" })).toBeVisible();
});

test("an admin fulfils a cash-on-delivery order", async ({ page }) => {
  await addToBag(page, POPLIN_SHIRT.slug, "L");
  const orderId = await checkoutCashOnDelivery(page, "Northfold Admin");

  await page.goto(`/admin/orders/${orderId}`);
  for (const [action, toast] of [
    ["Start processing", "Order marked processing"],
    ["Mark shipped", "Order marked shipped"],
    ["Mark delivered", "Order marked delivered"],
  ] as const) {
    await page.getByRole("button", { name: action }).click();
    await expect(page.getByText(toast)).toBeVisible();
  }
  // Cash is collected on delivery, so the order is now paid.
  await expect(page.getByText("Paid", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("This order is final; no further status changes.")).toBeVisible();
});
