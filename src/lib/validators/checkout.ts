import { z } from "zod";

import { PaymentMethod } from "@/generated/prisma/enums";

import { addressSchema, EMPTY_ADDRESS_INPUT } from "./address";
import { cartLinesSchema } from "./cart";
import { idSchema } from "./common";

export const shippingSelectionSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("saved"), addressId: idSchema }),
  z.object({
    type: z.literal("new"),
    address: addressSchema,
    saveAddress: z.boolean().default(false),
  }),
]);

export const placeOrderSchema = z.object({
  items: cartLinesSchema.refine((lines) => lines.length > 0, { error: "Your cart is empty" }),
  shipping: shippingSelectionSchema,
  paymentMethod: z.enum(PaymentMethod, { error: "Choose a payment method" }),
});
export type PlaceOrderInput = z.input<typeof placeOrderSchema>;
export type PlaceOrderData = z.output<typeof placeOrderSchema>;

/** Address fields as typed into a form, before validation. */
export const addressDraftSchema = z.object({
  fullName: z.string(),
  phone: z.string(),
  line1: z.string(),
  line2: z.string().optional(),
  city: z.string(),
  state: z.string(),
  postalCode: z.string(),
  country: z.string(),
});
export type AddressDraft = z.infer<typeof addressDraftSchema>;

export const EMPTY_ADDRESS: AddressDraft = EMPTY_ADDRESS_INPUT;

/**
 * The checkout form (client). `shippingChoice` is a saved address id or "new"; only a new
 * address is validated, with the same `addressSchema` the server uses.
 */
export const checkoutFormSchema = z
  .object({
    shippingChoice: z.string().min(1, { error: "Choose a shipping address" }),
    address: addressDraftSchema,
    saveAddress: z.boolean(),
    paymentMethod: z.enum(PaymentMethod, { error: "Choose a payment method" }),
  })
  .superRefine((value, ctx) => {
    if (value.shippingChoice !== "new") return;
    const result = addressSchema.safeParse(value.address);
    if (result.success) return;
    for (const issue of result.error.issues) {
      ctx.addIssue({ code: "custom", path: ["address", ...issue.path], message: issue.message });
    }
  });
export type CheckoutFormValues = z.infer<typeof checkoutFormSchema>;

/** Maps the form to the `placeOrder` payload; the server parses it with `placeOrderSchema`. */
export function toPlaceOrderInput(
  values: CheckoutFormValues,
  items: { variantId: string; quantity: number }[],
) {
  return {
    items,
    paymentMethod: values.paymentMethod,
    shipping:
      values.shippingChoice === "new"
        ? { type: "new" as const, address: values.address, saveAddress: values.saveAddress }
        : { type: "saved" as const, addressId: values.shippingChoice },
  };
}
