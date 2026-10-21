import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

// Deterministic, non-secret configuration so tests never depend on a developer's .env file.
const TEST_DATABASE_URL =
  process.env.TEST_DATABASE_URL ??
  "postgresql://northfold:northfold@localhost:5432/northfold_test?schema=public";

const testEnv = {
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

const serverOnlyStub = fileURLToPath(new URL("./tests/stubs/server-only.ts", import.meta.url));

export default defineConfig({
  resolve: {
    tsconfigPaths: true,
    alias: { "server-only": serverOnlyStub },
  },
  test: {
    env: testEnv,
    coverage: {
      provider: "v8",
      include: ["src/lib/**/*.ts", "src/server/**/*.ts", "src/stores/**/*.ts"],
      exclude: ["**/*.test.ts", "src/generated/**"],
      reporter: ["text", "html", "json-summary"],
      thresholds: { lines: 80, functions: 80, statements: 80, branches: 75 },
    },
    projects: [
      {
        extends: true,
        test: {
          name: "unit",
          environment: "node",
          setupFiles: ["./tests/setup-unit.ts"],
          include: ["src/**/*.test.ts"],
          exclude: ["src/**/*.int.test.ts"],
        },
      },
      {
        extends: true,
        test: {
          name: "integration",
          environment: "node",
          include: ["src/**/*.int.test.ts"],
          globalSetup: ["./tests/global-setup.ts"],
          setupFiles: ["./tests/setup-integration.ts"],
          // All integration files share one database, so they run one at a time.
          fileParallelism: false,
          testTimeout: 30_000,
          hookTimeout: 60_000,
        },
      },
    ],
  },
});
