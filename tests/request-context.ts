/**
 * The fake "current request" seen by `next/headers` in integration tests. Tests set the cookie
 * header to act as a given user (see tests/auth.ts).
 */
export const requestContext: { headers: Headers } = { headers: new Headers() };

export function resetRequestContext(): void {
  requestContext.headers = new Headers();
}
