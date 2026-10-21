import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

import { testEnv } from "./tests/test-env";

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
