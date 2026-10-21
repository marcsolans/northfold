import { beforeEach, describe, expect, it } from "vitest";

import { actAs, signInAs, signUpUser, TEST_PASSWORD } from "../../../tests/auth";
import { prisma, resetDatabase } from "../../../tests/db";

import { auth } from "./auth";
import { AuthorizationError, getCurrentUser, requireAdmin, requireUser } from "./session";

beforeEach(resetDatabase);

describe("requireUser", () => {
  it("rejects anonymous requests", async () => {
    actAs(null);
    await expect(requireUser()).rejects.toMatchObject({ reason: "unauthenticated" });
  });

  it("returns the signed-in user", async () => {
    const user = await signInAs("USER");
    await expect(requireUser()).resolves.toMatchObject({ id: user.id, role: "USER" });
  });
});

describe("requireAdmin", () => {
  it("rejects anonymous requests", async () => {
    actAs(null);
    await expect(requireAdmin()).rejects.toBeInstanceOf(AuthorizationError);
  });

  it("rejects signed-in customers", async () => {
    await signInAs("USER");
    await expect(requireAdmin()).rejects.toMatchObject({ reason: "forbidden" });
  });

  it("accepts admins", async () => {
    const admin = await signInAs("ADMIN");
    await expect(requireAdmin()).resolves.toMatchObject({ id: admin.id, role: "ADMIN" });
  });

  it("sees a demotion immediately, ignoring the session cookie cache", async () => {
    const admin = await signInAs("ADMIN");
    await prisma.user.update({ where: { id: admin.id }, data: { role: "USER" } });
    await expect(requireAdmin()).rejects.toMatchObject({ reason: "forbidden" });
  });
});

describe("role field", () => {
  it("cannot be set through sign-up", async () => {
    const result = await auth.api.signUpEmail({
      body: {
        name: "Mallory",
        email: "mallory@northfold.test",
        password: TEST_PASSWORD,
        ...({ role: "ADMIN" } as Record<string, string>),
      },
    });
    const stored = await prisma.user.findUniqueOrThrow({ where: { id: result.user.id } });
    expect(stored.role).toBe("USER");
  });

  it("cannot be set through a profile update", async () => {
    const session = await signUpUser();
    await expect(
      auth.api.updateUser({
        body: { ...({ role: "ADMIN" } as Record<string, string>) },
        headers: new Headers({ cookie: session.cookie }),
      }),
    ).rejects.toThrow();
    const stored = await prisma.user.findUniqueOrThrow({ where: { id: session.user.id } });
    expect(stored.role).toBe("USER");
  });
});

describe("rate limiting", () => {
  function signInRequest(ip: string) {
    return new Request("http://localhost:3000/api/auth/sign-in/email", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        origin: "http://localhost:3000",
        "x-forwarded-for": ip,
      },
      body: JSON.stringify({ email: "nobody@northfold.test", password: "wrong-password" }),
    });
  }

  it("blocks repeated sign-in attempts from one IP with 429", async () => {
    const statuses: number[] = [];
    for (let attempt = 0; attempt < 6; attempt++) {
      const response = await auth.handler(signInRequest("203.0.113.7"));
      statuses.push(response.status);
    }
    expect(statuses.slice(0, 5).every((status) => status === 401)).toBe(true);
    expect(statuses[5]).toBe(429);

    // A different client is unaffected.
    const other = await auth.handler(signInRequest("203.0.113.8"));
    expect(other.status).toBe(401);
  });
});

describe("getCurrentUser", () => {
  it("returns null without a session", async () => {
    actAs(null);
    await expect(getCurrentUser()).resolves.toBeNull();
  });
});
