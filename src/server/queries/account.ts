import "server-only";

import { prisma } from "@/lib/prisma";

/** Whether the user can sign in with a password (Google-only accounts cannot change one). */
export async function hasPasswordAccount(userId: string): Promise<boolean> {
  const count = await prisma.account.count({ where: { userId, providerId: "credential" } });
  return count > 0;
}

export async function getMemberSince(userId: string): Promise<string | null> {
  const user = await prisma.user.findUnique({ where: { id: userId }, select: { createdAt: true } });
  return user?.createdAt.toISOString() ?? null;
}
