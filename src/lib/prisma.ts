import "server-only";

import { env } from "@/env";
import type { PrismaClient } from "@/generated/prisma/client";

import { createPrismaClient } from "./prisma-client";

// Reuse one client across hot reloads in development instead of opening new pools.
const globalForPrisma = globalThis as unknown as { prisma?: PrismaClient };

export const prisma: PrismaClient = globalForPrisma.prisma ?? createPrismaClient(env.DATABASE_URL);

if (env.NODE_ENV !== "production") globalForPrisma.prisma = prisma;
