import { z } from "zod";

import { OrderStatus, PaymentMethod } from "@/generated/prisma/enums";

import { firstParam, idSchema, pageSchema, rawParam, type RawParam } from "./common";

export const updateOrderStatusSchema = z.object({
  orderId: idSchema,
  status: z.enum(OrderStatus, { error: "Unknown status" }),
});

export const orderIdSchema = z.object({ orderId: idSchema });

const optionalStatus = z.enum(OrderStatus).optional().catch(undefined);
const optionalPaymentMethod = z.enum(PaymentMethod).optional().catch(undefined);

export const adminOrderFiltersSchema = z.object({
  status: rawParam.transform((raw) => optionalStatus.parse(firstParam(raw))),
  payment: rawParam.transform((raw) => optionalPaymentMethod.parse(firstParam(raw))),
  q: rawParam.transform((raw) => firstParam(raw)?.trim().slice(0, 100) || undefined),
  page: rawParam.transform((raw) => pageSchema.parse(firstParam(raw))),
});
export type AdminOrderFilters = z.output<typeof adminOrderFiltersSchema>;

export function parseAdminOrderFilters(searchParams: Record<string, RawParam>): AdminOrderFilters {
  return adminOrderFiltersSchema.parse(searchParams);
}
