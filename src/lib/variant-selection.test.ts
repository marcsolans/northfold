import { describe, expect, it } from "vitest";

import {
  colorOptions,
  findVariant,
  initialColor,
  type SelectableVariant,
  sizeOptions,
} from "./variant-selection";

const variant = (
  id: string,
  colorName: string,
  size: SelectableVariant["size"],
  stock: number,
): SelectableVariant => ({ id, colorName, colorHex: "#000000", size, stock });

const variants = [
  variant("a", "Sand", "M", 0),
  variant("b", "Sand", "L", 3),
  variant("c", "Navy", "S", 0),
  variant("d", "Navy", "M", 0),
  variant("e", "Olive", "XL", 5),
];

describe("variant selection", () => {
  it("lists colours with stock flags", () => {
    expect(colorOptions(variants)).toEqual([
      { name: "Sand", hex: "#000000", inStock: true },
      { name: "Navy", hex: "#000000", inStock: false },
      { name: "Olive", hex: "#000000", inStock: true },
    ]);
  });

  it("orders sizes canonically and only enables existing, in-stock combinations", () => {
    const options = sizeOptions(variants, "Sand");
    expect(options.map((o) => o.size)).toEqual(["S", "M", "L", "XL"]);
    expect(options.map((o) => o.available)).toEqual([false, false, true, false]);
    expect(options[0]?.variant).toBeUndefined();
    expect(options[1]?.variant?.id).toBe("a");
  });

  it("finds the variant for a combination", () => {
    expect(findVariant(variants, "Olive", "XL")?.id).toBe("e");
    expect(findVariant(variants, "Olive", "S")).toBeUndefined();
    expect(findVariant(variants, null, "S")).toBeUndefined();
  });

  it("starts on the first colour that has stock", () => {
    expect(initialColor([variant("x", "Navy", "S", 0), ...variants])).toBe("Sand");
    expect(initialColor([variant("x", "Navy", "S", 0)])).toBe("Navy");
    expect(initialColor([])).toBeNull();
  });
});
