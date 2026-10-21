import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.doUnmock("@/env");
  vi.resetModules();
});

describe("getStripe", () => {
  it("creates one client and reuses it", async () => {
    const { getStripe } = await import("./stripe");
    expect(getStripe()).toBe(getStripe());
  });

  it("throws when Stripe is not configured", async () => {
    vi.doMock("@/env", () => ({ env: { STRIPE_SECRET_KEY: undefined } }));
    const { getStripe } = await import("./stripe");
    expect(() => getStripe()).toThrow("STRIPE_SECRET_KEY is not configured");
  });
});
