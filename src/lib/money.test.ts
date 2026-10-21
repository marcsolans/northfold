import { describe, expect, it } from "vitest";

import {
  formatMoney,
  fromCents,
  lineTotal,
  money,
  roundToCents,
  sumMoney,
  toCents,
  toMoneyString,
} from "./money";

describe("money", () => {
  it("avoids binary floating point errors", () => {
    expect(money("0.1").plus("0.2").equals("0.3")).toBe(true);
    expect(sumMoney(["0.1", "0.2", 0.3]).toFixed(2)).toBe("0.60");
  });

  it("accepts anything with a decimal toString (e.g. Prisma.Decimal)", () => {
    expect(money({ toString: () => "19.90" }).toFixed(2)).toBe("19.90");
  });

  it("rejects non-finite amounts", () => {
    expect(() => money("abc")).toThrow();
    expect(() => money(Number.POSITIVE_INFINITY)).toThrow(RangeError);
  });

  it("multiplies a unit price by an integer quantity", () => {
    expect(lineTotal("19.99", 3).toFixed(2)).toBe("59.97");
    expect(lineTotal("19.99", 0).toFixed(2)).toBe("0.00");
  });

  it("rejects fractional or negative quantities", () => {
    expect(() => lineTotal("10", 1.5)).toThrow(RangeError);
    expect(() => lineTotal("10", -1)).toThrow(RangeError);
  });

  it("rounds half up to cents", () => {
    expect(roundToCents("1.005").toFixed(2)).toBe("1.01");
    expect(roundToCents("1.004").toFixed(2)).toBe("1.00");
  });

  it("converts to and from integer cents exactly", () => {
    expect(toCents("19.99")).toBe(1999);
    expect(toCents("0.29")).toBe(29);
    expect(toCents("1234567.89")).toBe(123456789);
    expect(fromCents(1999).toFixed(2)).toBe("19.99");
    expect(() => fromCents(10.5)).toThrow(RangeError);
  });

  it("serialises to a fixed two-decimal string", () => {
    expect(toMoneyString(5)).toBe("5.00");
    expect(toMoneyString("12.345")).toBe("12.35");
  });

  it("formats as US dollars", () => {
    expect(formatMoney("1234.5")).toBe("$1,234.50");
    expect(formatMoney(0)).toBe("$0.00");
  });
});
