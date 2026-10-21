import { describe, expect, it } from "vitest";

import { suggestSku } from "./sku";
import { productVariantSchema } from "./validators/product";

describe("suggestSku", () => {
  it("builds a readable SKU from slug, size and colour", () => {
    expect(suggestSku("merino-rollneck", "M", "Oat")).toBe("NF-MR-ROL-M-OAT");
    expect(suggestSku("tee", "XL", "Fjord Navy")).toBe("NF-T-TEE-XL-FJO");
  });

  it("keeps products that share leading words apart", () => {
    expect(suggestSku("alpine-merino-scarf", "M", "Oat")).not.toBe(
      suggestSku("alpine-merino-beanie", "M", "Oat"),
    );
  });

  it("produces a SKU the variant schema accepts", () => {
    const sku = suggestSku("a-very-long-product-name-indeed", "XXL", "Heather Grey!");
    expect(
      productVariantSchema.safeParse({
        size: "XXL",
        colorName: "Heather Grey",
        colorHex: "#b9b8b3",
        sku,
        stock: 1,
      }).success,
    ).toBe(true);
  });

  it("copes with an empty slug or colour", () => {
    expect(suggestSku("", "S", "")).toBe("NF-S");
  });
});
