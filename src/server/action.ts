import "server-only";

import { unstable_rethrow } from "next/navigation";

import { type ActionResult, fail } from "@/lib/action-result";
import { logger } from "@/lib/logger";

import { AuthorizationError } from "./auth/session";

/** An error whose message is safe to show to the user (validation, business rules). */
export class UserFacingError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "UserFacingError";
  }
}

/**
 * Runs a Server Action body and turns every failure into a safe ActionResult:
 * authorization errors and UserFacingErrors keep their message, anything else is logged with
 * context and replaced by a generic message. Next.js control flow (redirect/notFound) is
 * re-thrown untouched.
 */
export async function runAction<T>(
  name: string,
  body: () => Promise<ActionResult<T>>,
): Promise<ActionResult<T>> {
  try {
    return await body();
  } catch (error) {
    unstable_rethrow(error);
    if (error instanceof AuthorizationError) return fail(error.message);
    if (error instanceof UserFacingError) return fail(error.message);
    logger.error("Server action failed", { action: name, error });
    return fail("Something went wrong. Please try again.");
  }
}
