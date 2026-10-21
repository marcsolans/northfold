import { z } from "zod";

import { optionalText, requiredText } from "./common";

/** Countries Northfold ships to (ISO 3166-1 alpha-2). */
export const SHIPPING_COUNTRIES = [
  "US",
  "CA",
  "GB",
  "IE",
  "DE",
  "FR",
  "ES",
  "IT",
  "NL",
  "SE",
  "NO",
  "DK",
  "FI",
  "AU",
  "NZ",
] as const;
export type ShippingCountry = (typeof SHIPPING_COUNTRIES)[number];

/** Narrows a stored country code to a supported one (falls back to the first). */
export function toShippingCountry(code: string): ShippingCountry {
  return SHIPPING_COUNTRIES.find((country) => country === code) ?? SHIPPING_COUNTRIES[0];
}

export const addressSchema = z.object({
  fullName: requiredText("Full name", 100),
  phone: z
    .string({ error: "Phone is required" })
    .trim()
    .regex(/^\+?[0-9][0-9\s().-]{5,19}$/, { error: "Enter a valid phone number" }),
  line1: requiredText("Address", 120),
  line2: optionalText(120),
  city: requiredText("City", 80),
  state: requiredText("State / region", 80),
  postalCode: z
    .string({ error: "Postal code is required" })
    .trim()
    .regex(/^[A-Za-z0-9][A-Za-z0-9\s-]{1,9}$/, { error: "Enter a valid postal code" }),
  country: z.enum(SHIPPING_COUNTRIES, { error: "Choose a country we ship to" }),
});
export type AddressInput = z.input<typeof addressSchema>;

export const EMPTY_ADDRESS_INPUT: AddressInput = {
  fullName: "",
  phone: "",
  line1: "",
  line2: "",
  city: "",
  state: "",
  postalCode: "",
  country: SHIPPING_COUNTRIES[0],
};
export type AddressData = z.output<typeof addressSchema>;

/** The address book form and actions: an address plus the "default" flag. */
export const savedAddressSchema = z.object({
  address: addressSchema,
  isDefault: z.boolean(),
});
export type SavedAddressInput = z.input<typeof savedAddressSchema>;
export type SavedAddressData = z.output<typeof savedAddressSchema>;
