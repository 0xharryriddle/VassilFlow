import { defineConfig, devices } from "@playwright/test";

const chromeExecutablePath = process.env.PLAYWRIGHT_CHROME_EXECUTABLE_PATH;
const webServerCommand =
  process.env.PLAYWRIGHT_WEB_SERVER_COMMAND ?? "pnpm build && pnpm start";
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000";
const webServerTimeout = Number.parseInt(
  process.env.PLAYWRIGHT_WEB_SERVER_TIMEOUT_MS ?? "",
  10,
);

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "github" : "html",
  timeout: 30_000,

  use: {
    baseURL,
    trace: "on-first-retry",
  },

  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        ...(chromeExecutablePath
          ? { launchOptions: { executablePath: chromeExecutablePath } }
          : {}),
      },
    },
  ],

  webServer: {
    command: webServerCommand,
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: Number.isFinite(webServerTimeout) ? webServerTimeout : 120_000,
    env: {
      SKIP_ENV_VALIDATION: "1",
      VASSILFLOW_AUTH_DISABLED: "1",
    },
  },
});
