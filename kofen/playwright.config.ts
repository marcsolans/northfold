import { defineConfig, devices } from "@playwright/test";

const PORT = Number(process.env.PORT ?? 3100);

/**
 * End-to-end checks against the production build.
 *   npm run build && npm run test:e2e
 * Screenshots land in artifacts/screenshots (gitignored).
 */
export default defineConfig({
  testDir: "tests/e2e",
  timeout: 90_000,
  fullyParallel: true,
  reporter: [["list"]],
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: "off",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], deviceScaleFactor: 1 } }],
  webServer: {
    command: `npx next start -p ${PORT}`,
    url: `http://localhost:${PORT}/en`,
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
