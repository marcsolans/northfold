import { inferAdditionalFields } from "better-auth/client/plugins";
import { createAuthClient } from "better-auth/react";

import type { auth } from "@/server/auth/auth";

/** Browser auth client. Calls go through /api/auth, where Better Auth's rate limits apply. */
export const authClient = createAuthClient({
  plugins: [inferAdditionalFields<typeof auth>()],
});
