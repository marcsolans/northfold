import { randomUUID } from "node:crypto";

import type { Role } from "@/generated/prisma/enums";
import { auth } from "@/server/auth/auth";

import { prisma } from "./db";
import { requestContext } from "./request-context";

export const TEST_PASSWORD = "correct-horse-battery";

/** Signs a user up through Better Auth and returns them with a cookie header for their session. */
export async function signUpUser(options: { role?: Role; email?: string; name?: string } = {}) {
  const email = options.email ?? `shopper-${randomUUID().slice(0, 8)}@northfold.test`;
  const { headers, response } = await auth.api.signUpEmail({
    body: { name: options.name ?? "Test Shopper", email, password: TEST_PASSWORD },
    returnHeaders: true,
  });
  if (options.role && options.role !== "USER") {
    await prisma.user.update({ where: { id: response.user.id }, data: { role: options.role } });
  }
  const cookie = headers
    .getSetCookie()
    .map((value) => value.split(";")[0])
    .join("; ");
  return { user: { ...response.user, role: options.role ?? "USER" }, cookie };
}

/** Makes subsequent server calls in this test run as the given user (or anonymously). */
export function actAs(session: { cookie: string } | null): void {
  requestContext.headers = new Headers(session ? { cookie: session.cookie } : {});
}

/** Shorthand: sign up a user with a role and act as them. */
export async function signInAs(role: Role = "USER") {
  const session = await signUpUser({ role });
  actAs(session);
  return session.user;
}
