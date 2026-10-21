/** Shared by playwright.config.ts and the setup project. */
export const E2E_PORT = Number(process.env.E2E_PORT ?? 3100);
export const E2E_BASE_URL = `http://localhost:${E2E_PORT}`;
export const E2E_DATABASE_URL =
  process.env.E2E_DATABASE_URL ??
  "postgresql://northfold:northfold@localhost:5432/northfold_e2e?schema=public";
