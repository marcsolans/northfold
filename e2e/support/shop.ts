import { type Page, expect } from "@playwright/test";

/** A seeded product under the free-shipping threshold ($89 + $10 shipping). */
export const POPLIN_SHIRT = {
  slug: "relaxed-poplin-shirt",
  name: "Relaxed Poplin Shirt",
  price: "$89.00",
} as const;

/** The value next to a label in an order summary (Subtotal, Shipping, Tax, Total). */
export function summaryValue(page: Page, label: string) {
  return page.locator(`dt:text-is("${label}") + dd`).filter({ visible: true }).first();
}

export async function addToBag(page: Page, slug: string, size: string) {
  await page.goto(`/products/${slug}`);
  // The size inputs are visually hidden behind styled labels.
  await page.getByRole("radio", { name: `Size ${size}`, exact: true }).check({ force: true });
  await page.getByRole("button", { name: "Add to bag" }).click();
  await expect(page.getByText("Added to your bag")).toBeVisible();
}

export async function fillShippingAddress(page: Page, fullName: string) {
  await page.getByLabel("Full name").fill(fullName);
  await page.getByLabel("Address", { exact: true }).fill("12 Analytical Way");
  await page.getByLabel("City").fill("Portland");
  await page.getByLabel("State / region").fill("OR");
  await page.getByLabel("Postal code").fill("97201");
  await page.getByLabel("Phone").fill("+1 555 010 2030");
}

/**
 * From a non-empty bag: checkout with cash on delivery and returns the order id. A first order
 * enters a new address; later ones use the default address saved by the first.
 */
export async function checkoutCashOnDelivery(page: Page, fullName: string): Promise<string> {
  await page.goto("/cart");
  await page.getByRole("link", { name: "Proceed to checkout" }).click();
  await expect(page).toHaveURL("/checkout");
  const addressForm = page.getByLabel("Full name");
  const savedAddresses = page.getByRole("radio", { name: "Use a new address" });
  await expect(addressForm.or(savedAddresses).first()).toBeVisible();
  if (await addressForm.isVisible()) await fillShippingAddress(page, fullName);
  await page.getByRole("radio", { name: /Cash on delivery/ }).check();
  await page.getByRole("button", { name: "Place order" }).click();
  await expect(page).toHaveURL(/\/checkout\/success\?order=/);
  await expect(page.getByRole("heading", { name: /your order is confirmed/i })).toBeVisible();
  const orderId = new URL(page.url()).searchParams.get("order");
  expect(orderId).toBeTruthy();
  return orderId ?? "";
}
