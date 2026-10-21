import { SHIPPING_COUNTRIES } from "./validators/address";

const regionNames = new Intl.DisplayNames(["en"], { type: "region" });

export function countryName(code: string): string {
  return regionNames.of(code) ?? code;
}

export const COUNTRY_OPTIONS = SHIPPING_COUNTRIES.map((code) => ({
  value: code,
  label: countryName(code),
}));
