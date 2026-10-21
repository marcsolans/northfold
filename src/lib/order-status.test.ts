import { describe, expect, it } from "vitest";

import { OrderStatus } from "@/generated/prisma/enums";

import {
  allowedTransitions,
  assertTransition,
  canTransition,
  InvalidOrderTransitionError,
  isTerminalStatus,
} from "./order-status";

const ALL = Object.values(OrderStatus);

const VALID: ReadonlyArray<[OrderStatus, OrderStatus]> = [
  ["PENDING", "PROCESSING"],
  ["PENDING", "CANCELLED"],
  ["PROCESSING", "SHIPPED"],
  ["PROCESSING", "CANCELLED"],
  ["SHIPPED", "DELIVERED"],
];

const isValid = (from: OrderStatus, to: OrderStatus) =>
  VALID.some(([f, t]) => f === from && t === to);

const INVALID = ALL.flatMap((from) =>
  ALL.filter((to) => !isValid(from, to)).map((to) => [from, to] as const),
);

describe("order status state machine", () => {
  it.each(VALID)("allows %s → %s", (from, to) => {
    expect(canTransition(from, to)).toBe(true);
    expect(() => assertTransition(from, to)).not.toThrow();
  });

  it.each(INVALID)("rejects %s → %s", (from, to) => {
    expect(canTransition(from, to)).toBe(false);
    expect(() => assertTransition(from, to)).toThrow(InvalidOrderTransitionError);
  });

  it("covers every pair of statuses", () => {
    expect(VALID.length + INVALID.length).toBe(ALL.length * ALL.length);
  });

  it("treats delivered and cancelled as terminal", () => {
    expect(isTerminalStatus("DELIVERED")).toBe(true);
    expect(isTerminalStatus("CANCELLED")).toBe(true);
    expect(isTerminalStatus("PENDING")).toBe(false);
    expect(allowedTransitions("SHIPPED")).toEqual(["DELIVERED"]);
  });

  it("explains the rejected transition", () => {
    expect(() => assertTransition("DELIVERED", "PENDING")).toThrow(
      "Cannot change an order from DELIVERED to PENDING",
    );
  });
});
