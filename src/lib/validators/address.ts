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
export type AddressData = z.output<typeof addressSchema>;

export const addressFormSchema = addressSchema.extend({
  isDefault: z.boolean().default(false),
});
export type AddressFormInput = z.input<typeof addressFormSchema>;
export type AddressFormData = z.output<typeof addressFormSchema>;
