/**
 * The single result shape returned by every Server Action. Errors carry a message that is
 * safe to show to the user; internal details are logged on the server, never returned.
 */
export type ActionResult<T = void> =
  | { ok: true; data: T }
  | { ok: false; error: string; fieldErrors?: Record<string, string[] | undefined> };

export function ok(): ActionResult<void>;
export function ok<T>(data: T): ActionResult<T>;
export function ok<T>(data?: T): ActionResult<T | undefined> {
  return { ok: true, data };
}

export function fail(
  error: string,
  fieldErrors?: Record<string, string[] | undefined>,
): { ok: false; error: string; fieldErrors?: Record<string, string[] | undefined> } {
  return fieldErrors ? { ok: false, error, fieldErrors } : { ok: false, error };
}
