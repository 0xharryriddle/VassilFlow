import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000";
const replayGatewayPort = Number(
  process.env.PLAYWRIGHT_REPLAY_GATEWAY_PORT ?? "8011",
);
if (
  !Number.isInteger(replayGatewayPort) ||
  replayGatewayPort < 1 ||
  replayGatewayPort > 65535
) {
  throw new Error("PLAYWRIGHT_REPLAY_GATEWAY_PORT must be a valid TCP port");
}
const replayGatewayURL = `http://127.0.0.1:${replayGatewayPort}`;

/**
 * Layer 2 of the record/replay e2e: the REAL Next.js frontend rendering data
 * from a REAL gateway whose LLM is the deterministic `ReplayChatModel` (no API
 * key). This is separate from `playwright.config.ts` (which mocks the backend)
 * so the mock-based suite is untouched.
 *
 * By default, two webServers start: the replay gateway (:8011) and the frontend
 * (:3000, pointed at the gateway). The gateway loads generic chat replay
 * fixtures. Specs register throwaway accounts when they need a stable
 * user-scoped workspace.
 * PLAYWRIGHT_BASE_URL and PLAYWRIGHT_REPLAY_GATEWAY_PORT select isolated
 * endpoints; command overrides let callers use matching ports and local runtimes.
 */
export default defineConfig({
  testDir: "./tests/e2e-real-backend",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? "github" : "html",
  timeout: 90_000,

  use: {
    baseURL,
    trace: "on-first-retry",
  },

  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],

  webServer: [
    {
      command:
        process.env.PLAYWRIGHT_REPLAY_GATEWAY_COMMAND ??
        `uv run python scripts/run_replay_gateway.py --port ${replayGatewayPort} --cors ${new URL(baseURL).origin}`,
      cwd: "../backend",
      url: `${replayGatewayURL}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      stdout: "pipe",
      stderr: "pipe",
      // Mount the test-only run/message seeder used by multi-run-order.spec.ts
      // (#3352). The endpoint exists only on this replay gateway, never in the
      // production app.
      env: {
        VASSILFLOW_ENABLE_TEST_SEED: "1",
        VASSILFLOW_AUTH_DISABLED: "1",
      },
    },
    {
      command:
        process.env.PLAYWRIGHT_WEB_SERVER_COMMAND ?? "pnpm build && pnpm start",
      url: baseURL,
      reuseExistingServer: !process.env.CI,
      timeout: 240_000,
      env: {
        SKIP_ENV_VALIDATION: "1",
        VASSILFLOW_AUTH_DISABLED: "1",
        BETTER_AUTH_SECRET: "local-dev-secret",
        // Leave NEXT_PUBLIC_* unset so the frontend uses its built-in
        // next.config rewrites (same-origin proxy) instead of talking to the
        // gateway cross-origin — cross-origin fetches drop the auth cookies.
        // Just point that proxy at the replay gateway.
        VASSILFLOW_INTERNAL_GATEWAY_BASE_URL: replayGatewayURL,
      },
    },
  ],
});
