import { randomUUID } from "node:crypto";

import { beforeEach, describe, expect, it } from "vitest";

import { signUpUser } from "../../../tests/auth";
import { prisma, resetDatabase } from "../../../tests/db";
import { createAddress, createUser } from "../../../tests/factories";

import { getMemberSince, hasPasswordAccount } from "./account";
import { getUserAddresses } from "./addresses";

beforeEach(resetDatabase);

describe("hasPasswordAccount", () => {
  it("is true for email sign-ups and false for Google-only accounts", async () => {
    const { user } = await signUpUser();
    expect(await hasPasswordAccount(user.id)).toBe(true);

    const googleUser = await createUser();
    await prisma.account.create({
      data: { id: randomUUID(), userId: googleUser.id, providerId: "google", accountId: "g-1" },
    });
    expect(await hasPasswordAccount(googleUser.id)).toBe(false);
  });
});

describe("getMemberSince", () => {
  it("returns the sign-up date, or null for an unknown user", async () => {
    const user = await createUser();
    expect(await getMemberSince(user.id)).toBe(user.createdAt.toISOString());
    expect(await getMemberSince("missing")).toBeNull();
  });
});

describe("getUserAddresses", () => {
  it("lists only the customer's addresses, default first", async () => {
    const [user, other] = await Promise.all([createUser(), createUser()]);
    const first = await createAddress(user.id);
    const defaultAddress = await createAddress(user.id, true);
    const newest = await createAddress(user.id);
    await createAddress(other.id, true);

    const addresses = await getUserAddresses(user.id);
    expect(addresses.map((address) => address.id)).toEqual([
      defaultAddress.id,
      newest.id,
      first.id,
    ]);
    expect(addresses[0]).not.toHaveProperty("userId");
  });
});
