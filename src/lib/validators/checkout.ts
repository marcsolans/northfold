import { z } from "zod";

import { PaymentMethod } from "@/generated/prisma/enums";

import { addressSchema } from "./address";
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
