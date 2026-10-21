/** Deterministic, non-secret configuration for the Vitest run. */
export const TEST_DATABASE_URL =
  process.env.TEST_DATABASE_URL ??
  "postgresql://northfold:northfold@localhost:5432/northfold_test?schema=public";

export const testEnv = {
  DATABASE_URL: TEST_DATABASE_URL,
  DIRECT_URL: TEST_DATABASE_URL,
  BETTER_AUTH_SECRET: "test-secret-test-secret-test-secret-0123456789",
  BETTER_AUTH_URL: "http://localhost:3000",
  NEXT_PUBLIC_APP_URL: "http://localhost:3000",
  STRIPE_SECRET_KEY: "sk_test_northfold_unit_tests",
  STRIPE_WEBHOOK_SECRET: "whsec_northfold_unit_tests",
  ADMIN_EMAILS: "admin@northfold.test",
  GOOGLE_CLIENT_ID: "",
  GOOGLE_CLIENT_SECRET: "",
  CLOUDINARY_CLOUD_NAME: "",
  CLOUDINARY_API_KEY: "",
  CLOUDINARY_API_SECRET: "",
};
