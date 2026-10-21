import { beforeEach, describe, expect, it } from "vitest";

import { actAs, signInAs } from "../../../tests/auth";
import { resetDatabase } from "../../../tests/db";
import { createOrder, createUser } from "../../../tests/factories";

import { getOrderPaymentState } from "./orders";

beforeEach(resetDatabase);

describe("getOrderPaymentState", () => {
  it("returns the state of the customer's own order", async () => {
    const user = await signInAs("USER");
    const order = await createOrder(user.id, { paymentMethod: "STRIPE", paymentStatus: "PAID" });
    await expect(getOrderPaymentState({ orderId: order.id })).resolves.toEqual({
      ok: true,
      data: { status: "PENDING", paymentStatus: "PAID" },
    });
  });

  it("does not reveal other customers' orders or accept bad input", async () => {
    const owner = await createUser();
    const order = await createOrder(owner.id);
    await signInAs("USER");
    const notFound = { ok: false, error: "Order not found." };
    await expect(getOrderPaymentState({ orderId: order.id })).resolves.toEqual(notFound);
    await expect(getOrderPaymentState({ orderId: "" })).resolves.toEqual(notFound);
    await expect(getOrderPaymentState("nope")).resolves.toEqual(notFound);
  });

  it("requires a signed-in user", async () => {
    actAs(null);
    await expect(getOrderPaymentState({ orderId: "x" })).resolves.toMatchObject({ ok: false });
  });
});
