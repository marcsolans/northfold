import "server-only";

import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { cache } from "react";

import type { Role } from "@/generated/prisma/enums";

import { auth } from "./auth";

export interface SessionUser {
  id: string;
  name: string;
  email: string;
  role: Role;
}

export class AuthorizationError extends Error {
  constructor(readonly reason: "unauthenticated" | "forbidden") {
    super(
      reason === "unauthenticated" ? "You need to sign in." : "You are not allowed to do that.",
    );
    this.name = "AuthorizationError";
  }
}

function toSessionUser(user: { id: string; name: string; email: string; role: Role }): SessionUser {
  return { id: user.id, name: user.name, email: user.email, role: user.role };
}

/**
 * The signed-in user for this request, or null. Deduplicated per request with React.cache.
 * Identity may come from Better Auth's short-lived cookie cache.
 */
export const getCurrentUser = cache(async (): Promise<SessionUser | null> => {
  const session = await auth.api.getSession({ headers: await headers() });
  return session ? toSessionUser(session.user) : null;
});

/**
 * Same as getCurrentUser but always reads the session (and the role) from the database, so a
 * revoked session or a demoted admin takes effect immediately.
 */
const getFreshUser = cache(async (): Promise<SessionUser | null> => {
  const session = await auth.api.getSession({
    headers: await headers(),
    query: { disableCookieCache: true },
  });
  return session ? toSessionUser(session.user) : null;
});

/** For Server Actions and route handlers: throws AuthorizationError when not signed in. */
export async function requireUser(): Promise<SessionUser> {
  const user = await getCurrentUser();
  if (!user) throw new AuthorizationError("unauthenticated");
  return user;
}

/** For admin Server Actions and route handlers: throws unless the user is an ADMIN. */
export async function requireAdmin(): Promise<SessionUser> {
  const user = await getFreshUser();
  if (!user) throw new AuthorizationError("unauthenticated");
  if (user.role !== "ADMIN") throw new AuthorizationError("forbidden");
  return user;
}

export function signInPath(redirectTo: string): string {
  return `/sign-in?redirectTo=${encodeURIComponent(redirectTo)}`;
}

/** For pages: redirects to sign-in (and back afterwards) when not signed in. */
export async function requireUserPage(redirectTo: string): Promise<SessionUser> {
  const user = await getCurrentUser();
  if (!user) redirect(signInPath(redirectTo));
  return user;
}

/** For admin pages: anonymous users go to sign-in, signed-in non-admins go home. */
export async function requireAdminPage(redirectTo = "/admin"): Promise<SessionUser> {
  const user = await getFreshUser();
  if (!user) redirect(signInPath(redirectTo));
  if (user.role !== "ADMIN") redirect("/");
  return user;
}
