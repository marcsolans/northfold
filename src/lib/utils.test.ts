import { describe, expect, it } from "vitest";

import { cn, humanizeEnum, pluralize, slugify } from "./utils";

describe("cn", () => {
  it("joins class names and skips falsy values", () => {
    expect(cn("a", false, null, undefined, "", "b")).toBe("a b");
  });
});

describe("slugify", () => {
  it("lowercases, strips accents and collapses separators", () => {
    expect(slugify("  Crème Brûlée — Wool Coat!  ")).toBe("creme-brulee-wool-coat");
  });

  it("returns an empty string when nothing is left", () => {
    expect(slugify("¿?!")).toBe("");
  });
});

describe("pluralize", () => {
  it("uses the singular only for exactly one", () => {
    expect(pluralize(1, "order")).toBe("1 order");
    expect(pluralize(0, "order")).toBe("0 orders");
    expect(pluralize(2, "address", "addresses")).toBe("2 addresses");
  });
});

describe("humanizeEnum", () => {
  it("turns SCREAMING_SNAKE values into sentence case", () => {
    expect(humanizeEnum("CASH_ON_DELIVERY")).toBe("Cash on delivery");
    expect(humanizeEnum("PAID")).toBe("Paid");
  });
});
