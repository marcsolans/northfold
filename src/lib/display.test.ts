import { describe, expect, it } from "vitest";

import { CATEGORY_IMAGES, HERO_IMAGE, SECONDARY_HERO_IMAGE } from "./brand-images";
import { COUNTRY_OPTIONS, countryName } from "./countries";
import { formatDate, formatDateTime } from "./format";
import { isAllowedImageUrl } from "./image-validation";
import { categoryHref, STORE_NAV } from "./navigation";
import { orderNumber } from "./orders";
import { SHIPPING_COUNTRIES } from "./validators/address";

/** ICU may use narrow no-break spaces before AM/PM. */
const normalizeSpaces = (value: string) => value.replace(/\s/g, " ");

describe("formatDate / formatDateTime", () => {
  it("formats in UTC regardless of the server's time zone", () => {
    expect(formatDate("2026-10-21T23:30:00.000Z")).toBe("Oct 21, 2026");
    expect(formatDate(new Date("2026-01-01T00:00:00.000Z"))).toBe("Jan 1, 2026");
    expect(normalizeSpaces(formatDateTime("2026-10-21T09:06:00.000Z"))).toBe(
      "Oct 21, 2026, 9:06 AM UTC",
    );
  });
});

describe("orderNumber", () => {
  it("uses the last eight characters of the id, uppercased", () => {
    expect(orderNumber("cmvhx084y0002me7drqnw1kwz")).toBe("NF-RQNW1KWZ");
  });
});

describe("countries", () => {
  it("names every shipping country", () => {
    expect(countryName("GB")).toBe("United Kingdom");
    expect(COUNTRY_OPTIONS.map((option) => option.value)).toEqual([...SHIPPING_COUNTRIES]);
    for (const option of COUNTRY_OPTIONS) expect(option.label).not.toBe(option.value);
  });
});

describe("navigation", () => {
  it("links categories to the filtered shop", () => {
    expect(categoryHref("CHILDREN")).toBe("/shop?category=children");
    expect(STORE_NAV.map((item) => item.href)).toContain("/shop?category=women");
  });
});

describe("brand images", () => {
  it("come from hosts that next/image and the CSP allow", () => {
    const urls = [HERO_IMAGE, SECONDARY_HERO_IMAGE, ...Object.values(CATEGORY_IMAGES)].map(
      (image) => image.src,
    );
    for (const url of urls) expect(isAllowedImageUrl(url)).toBe(true);
  });
});
