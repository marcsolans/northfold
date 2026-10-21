import { describe, expect, it } from "vitest";

import {
  amountUntilFreeShipping,
  calculateShipping,
  calculateTax,
  calculateTotals,
} from "./pricing";

describe("calculateShipping", () => {
  it("is free for an empty cart", () => {
    expect(calculateShipping(0).toFixed(2)).toBe("0.00");
  });

  it("charges the flat fee below the threshold", () => {
    expect(calculateShipping("0.01").toFixed(2)).toBe("10.00");
    expect(calculateShipping("99.99").toFixed(2)).toBe("10.00");
  });

  it("is free at or above the threshold", () => {
    expect(calculateShipping("100.00").toFixed(2)).toBe("0.00");
    expect(calculateShipping("250").toFixed(2)).toBe("0.00");
  });
});

describe("calculateTax", () => {
  it("uses the configured rate (0%)", () => {
    expect(calculateTax("123.45").toFixed(2)).toBe("0.00");
  });
});

describe("calculateTotals", () => {
  it("adds shipping below the threshold", () => {
    const totals = calculateTotals([
      { unitPrice: "29.90", quantity: 2 },
      { unitPrice: "15.00", quantity: 1 },
    ]);
    expect(totals.subtotal.toFixed(2)).toBe("74.80");
    expect(totals.shippingFee.toFixed(2)).toBe("10.00");
    expect(totals.tax.toFixed(2)).toBe("0.00");
    expect(totals.total.toFixed(2)).toBe("84.80");
  });

  it("ships free once the subtotal reaches the threshold", () => {
    const totals = calculateTotals([{ unitPrice: "50.00", quantity: 2 }]);
    expect(totals.shippingFee.toFixed(2)).toBe("0.00");
    expect(totals.total.toFixed(2)).toBe("100.00");
  });

  it("returns zeros for no lines", () => {
    const totals = calculateTotals([]);
    expect(totals.total.toFixed(2)).toBe("0.00");
  });
});

describe("amountUntilFreeShipping", () => {
  it("returns the remaining amount, never negative", () => {
    expect(amountUntilFreeShipping("60").toFixed(2)).toBe("40.00");
    expect(amountUntilFreeShipping("100").toFixed(2)).toBe("0.00");
    expect(amountUntilFreeShipping("180").toFixed(2)).toBe("0.00");
  });
});
