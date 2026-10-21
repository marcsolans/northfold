import { defineConfig, devices } from "@playwright/test";

import { E2E_BASE_URL as BASE_URL, E2E_DATABASE_URL, E2E_PORT as PORT } from "./e2e/support/env";

// A preinstalled Chromium can be used instead of Playwright's download (e.g. in sandboxes).
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: executablePath ? { executablePath } : {},
  },
  projects: [
    { name: "setup", testMatch: /global\.setup\.ts/ },
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
      dependencies: ["setup"],
      testIgnore: /.*\.mobile\.spec\.ts/,
    },
    {
      name: "mobile",
      use: { ...devices["Pixel 7"], viewport: { width: 375, height: 812 } },
      dependencies: ["setup"],
      testMatch: /.*\.mobile\.spec\.ts/,
    },
  ],
  webServer: {
    // Fresh database + production build, so the suite exercises what ships.
    command: "bash scripts/e2e-server.sh",
    url: BASE_URL,
    timeout: 300_000,
    reuseExistingServer: !process.env.CI,
    stdout: "pipe",
    env: {
      PORT: String(PORT),
      DATABASE_URL: E2E_DATABASE_URL,
      DIRECT_URL: E2E_DATABASE_URL,
      NEXT_PUBLIC_APP_URL: BASE_URL,
      BETTER_AUTH_URL: BASE_URL,
      BETTER_AUTH_SECRET: "e2e-secret-e2e-secret-e2e-secret-0123456789",
      ADMIN_EMAILS: "admin@northfold.test",
    },
  },
});
