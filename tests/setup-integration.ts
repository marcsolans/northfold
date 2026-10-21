import { afterEach, vi } from "vitest";

import { requestContext, resetRequestContext } from "./request-context";

// Server modules read the request through next/headers; outside Next.js there is no request
// scope, so it is backed by a per-test fake.
vi.mock("next/headers", () => ({
  headers: async () => requestContext.headers,
  cookies: async () => ({
    get: (name: string) => {
      const cookie = requestContext.headers.get("cookie") ?? "";
      const match = cookie.split("; ").find((part) => part.startsWith(`${name}=`));
      return match ? { name, value: match.slice(name.length + 1) } : undefined;
    },
    getAll: () => [],
    has: () => false,
    set: () => undefined,
    delete: () => undefined,
  }),
}));

// Cache invalidation only means something inside a running Next.js server.
vi.mock("next/cache", () => ({
  cacheLife: vi.fn(),
  cacheTag: vi.fn(),
  revalidatePath: vi.fn(),
  revalidateTag: vi.fn(),
  updateTag: vi.fn(),
  refresh: vi.fn(),
}));

afterEach(() => {
  resetRequestContext();
});
