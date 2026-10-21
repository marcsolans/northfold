import { expect, test } from "@playwright/test";

import { STORAGE_STATE } from "./support/accounts";
import { addToBag, checkoutCashOnDelivery, POPLIN_SHIRT, summaryValue } from "./support/shop";

test.use({ storageState: STORAGE_STATE.customer });

test("browse, filter and pay on delivery, then find and cancel the order", async ({ page }) => {
  // Browse: category from the navigation, then a product type filter.
  await page.goto("/");
  await page
    .getByRole("navigation", { name: "Main" })
    .getByRole("link", { name: "Women", exact: true })
    .click();
  await expect(page).toHaveURL("/shop?category=women");
  const filters = page.getByRole("complementary", { name: "Filters" });
  await filters.getByRole("checkbox", { name: "Shirts", exact: true }).check();
  await expect(page).toHaveURL("/shop?category=women&type=shirt");
  const results = page.getByRole("region", { name: "Products" });
  await results.getByRole("link", { name: POPLIN_SHIRT.name }).first().click();
  await expect(page).toHaveURL(`/products/${POPLIN_SHIRT.slug}`);
  await expect(page.getByRole("heading", { level: 1, name: POPLIN_SHIRT.name })).toBeVisible();

  // Bag: $89 is below the $100 threshold, so shipping is $10.
  await addToBag(page, POPLIN_SHIRT.slug, "M");
  await page.goto("/cart");
  await expect(page.getByRole("link", { name: POPLIN_SHIRT.name }).first()).toBeVisible();
  await expect(summaryValue(page, "Subtotal")).toHaveText("$89.00");
  await expect(summaryValue(page, "Shipping")).toHaveText("$10.00");
  await expect(summaryValue(page, "Total")).toHaveText("$99.00");

  // Checkout with cash on delivery; the bag is cleared once the order exists.
  const orderId = await checkoutCashOnDelivery(page, "Ada Lovelace");
  await expect(summaryValue(page, "Total")).toHaveText("$99.00");
  await expect(page.getByTestId("cart-count")).toHaveCount(0);

  // The order is in the account, and a pending COD order can be cancelled.
  await page.goto("/account/orders");
  const reference = `NF-${orderId.slice(-8).toUpperCase()}`;
  await page.getByRole("link", { name: reference }).click();
  await expect(page).toHaveURL(`/account/orders/${orderId}`);
  await page.getByRole("button", { name: "Cancel order" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Cancel order" }).click();
  await expect(page.getByText("Your order has been cancelled.")).toBeVisible();
  await expect(page.getByText(/^Cancelled on/)).toBeVisible();
});

test("prices in the stored bag are not trusted", async ({ page }) => {
  await addToBag(page, POPLIN_SHIRT.slug, "S");
  // Tamper with the persisted cart: the bag lives in localStorage and can be edited.
  await page.evaluate(() => {
    const key = "northfold-cart";
    const stored = JSON.parse(window.localStorage.getItem(key) ?? "{}") as {
      state?: { lines?: { snapshot: { unitPrice: string } }[] };
    };
    for (const line of stored.state?.lines ?? []) line.snapshot.unitPrice = "1.00";
    window.localStorage.setItem(key, JSON.stringify(stored));
  });

  await page.goto("/cart");
  await expect(
    page.getByText(`The price of ${POPLIN_SHIRT.name}`, { exact: false }).first(),
  ).toBeVisible();
  await expect(summaryValue(page, "Subtotal")).toHaveText("$89.00");

  // Even an order placed straight away is priced from the database.
  await checkoutCashOnDelivery(page, "Ada Lovelace");
  await expect(summaryValue(page, "Subtotal")).toHaveText("$89.00");
  await expect(summaryValue(page, "Total")).toHaveText("$99.00");
});
