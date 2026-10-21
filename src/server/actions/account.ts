"use server";

import { revalidatePath, revalidateTag } from "next/cache";
import { headers } from "next/headers";

import type { Prisma } from "@/generated/prisma/client";
import { type ActionResult, fail, ok } from "@/lib/action-result";
import { CACHE_TAGS } from "@/lib/cache-tags";
import { prisma } from "@/lib/prisma";
import { savedAddressSchema } from "@/lib/validators/address";
import { updateProfileSchema } from "@/lib/validators/auth";
import { fieldErrorsFrom, idSchema } from "@/lib/validators/common";
import { orderIdSchema } from "@/lib/validators/order";
import { runAction, UserFacingError } from "@/server/action";
import { auth } from "@/server/auth/auth";
import { requireUser } from "@/server/auth/session";
import { restockItems } from "@/server/orders/stock";

// ─── Profile ────────────────────────────────────────────────────────────────

export async function updateProfile(input: unknown): Promise<ActionResult> {
  return runAction("updateProfile", async () => {
    await requireUser();
    const parsed = updateProfileSchema.safeParse(input);
    if (!parsed.success) return fail("Please check your name.", fieldErrorsFrom(parsed.error));
    // Through Better Auth so the session cookie cache is refreshed with the new name.
    await auth.api.updateUser({ body: { name: parsed.data.name }, headers: await headers() });
    revalidatePath("/account", "layout");
    return ok();
  });
}

// ─── Addresses ──────────────────────────────────────────────────────────────

async function makeDefault(tx: Prisma.TransactionClient, userId: string, addressId: string) {
  await tx.address.updateMany({ where: { userId, isDefault: true }, data: { isDefault: false } });
  await tx.address.update({ where: { id: addressId }, data: { isDefault: true } });
}

export async function createAddress(input: unknown): Promise<ActionResult<{ id: string }>> {
  return runAction("createAddress", async () => {
    const user = await requireUser();
    const parsed = savedAddressSchema.safeParse(input);
    if (!parsed.success) return fail("Please check the address.", fieldErrorsFrom(parsed.error));
    const { address, isDefault } = parsed.data;

    const created = await prisma.$transaction(async (tx) => {
      const count = await tx.address.count({ where: { userId: user.id } });
      const row = await tx.address.create({
        data: { ...address, line2: address.line2 ?? null, userId: user.id, isDefault: false },
      });
      // The first address is always the default.
      if (isDefault || count === 0) await makeDefault(tx, user.id, row.id);
      return row;
    });
    revalidatePath("/account/addresses");
    return ok({ id: created.id });
  });
}

export async function updateAddress(addressId: unknown, input: unknown): Promise<ActionResult> {
  return runAction("updateAddress", async () => {
    const user = await requireUser();
    const id = idSchema.safeParse(addressId);
    const parsed = savedAddressSchema.safeParse(input);
    if (!id.success) return fail("Address not found.");
    if (!parsed.success) return fail("Please check the address.", fieldErrorsFrom(parsed.error));
    const { address, isDefault } = parsed.data;

    await prisma.$transaction(async (tx) => {
      // Ownership: the update only matches the customer's own address.
      const { count } = await tx.address.updateMany({
        where: { id: id.data, userId: user.id },
        data: { ...address, line2: address.line2 ?? null },
      });
      if (count === 0) throw new UserFacingError("Address not found.");
      if (isDefault) await makeDefault(tx, user.id, id.data);
    });
    revalidatePath("/account/addresses");
    return ok();
  });
}

export async function setDefaultAddress(addressId: unknown): Promise<ActionResult> {
  return runAction("setDefaultAddress", async () => {
    const user = await requireUser();
    const id = idSchema.safeParse(addressId);
    if (!id.success) return fail("Address not found.");
    await prisma.$transaction(async (tx) => {
      const owned = await tx.address.findFirst({
        where: { id: id.data, userId: user.id },
        select: { id: true },
      });
      if (!owned) throw new UserFacingError("Address not found.");
      await makeDefault(tx, user.id, owned.id);
    });
    revalidatePath("/account/addresses");
    return ok();
  });
}

export async function deleteAddress(addressId: unknown): Promise<ActionResult> {
  return runAction("deleteAddress", async () => {
    const user = await requireUser();
    const id = idSchema.safeParse(addressId);
    if (!id.success) return fail("Address not found.");
    await prisma.$transaction(async (tx) => {
      const address = await tx.address.findFirst({ where: { id: id.data, userId: user.id } });
      if (!address) throw new UserFacingError("Address not found.");
      await tx.address.delete({ where: { id: address.id } });
      if (address.isDefault) {
        // Keep exactly one default while any address remains.
        const next = await tx.address.findFirst({
          where: { userId: user.id },
          orderBy: { createdAt: "desc" },
        });
        if (next) await tx.address.update({ where: { id: next.id }, data: { isDefault: true } });
      }
    });
    revalidatePath("/account/addresses");
    return ok();
  });
}

// ─── Orders ─────────────────────────────────────────────────────────────────

/**
 * Customers may cancel their own cash-on-delivery orders while they are still PENDING. The
 * status change and the restock happen in one transaction.
 */
export async function cancelOrder(input: unknown): Promise<ActionResult> {
  return runAction("cancelOrder", async () => {
    const user = await requireUser();
    const parsed = orderIdSchema.safeParse(input);
    if (!parsed.success) return fail("Order not found.");

    await prisma.$transaction(async (tx) => {
      const order = await tx.order.findFirst({
        where: { id: parsed.data.orderId, userId: user.id },
        include: { items: { select: { variantId: true, quantity: true } } },
      });
      if (!order) throw new UserFacingError("Order not found.");
      // Customers get a narrower rule than the state machine: only unconfirmed COD orders.
      if (order.paymentMethod !== "CASH_ON_DELIVERY" || order.status !== "PENDING") {
        throw new UserFacingError("This order can no longer be cancelled.");
      }
      // Conditional: a concurrent admin update (e.g. to PROCESSING) wins.
      const { count } = await tx.order.updateMany({
        where: { id: order.id, status: "PENDING" },
        data: { status: "CANCELLED", cancelledAt: new Date(), stockDeducted: false },
      });
      if (count === 0) throw new UserFacingError("This order can no longer be cancelled.");
      if (order.stockDeducted) await restockItems(tx, order.items);
    });

    revalidateTag(CACHE_TAGS.products, "max");
    revalidatePath(`/account/orders/${parsed.data.orderId}`);
    return ok();
  });
}
