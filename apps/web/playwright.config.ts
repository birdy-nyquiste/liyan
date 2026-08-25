import { defineConfig, devices } from "@playwright/test";

/**
 * The browser half of the Phase 1 release gate.
 *
 * One suite, two places to point it. Against Staging it proves the deployment:
 * real Supabase OTP, real DeepSeek, a real Blog. Locally it proves the
 * workbench: the same specs, the same server code, against a disposable
 * database with the identity provider and the paid providers substituted
 * (`scripts/e2e_server.py`).
 *
 * The local run is not a smaller Staging. It cannot tell you that a Supabase
 * project is configured, that DeepSeek answers, or that a Blog accepts a
 * Preview — which is exactly why the Staging run is the one the gate requires,
 * and this one is what keeps the suite honest between releases.
 *
 *     npm run test:e2e                              # local, starts everything
 *     LIYAN_E2E_BASE_URL=https://… \
 *     LIYAN_E2E_EMAIL=… LIYAN_E2E_OTP=… \
 *     npm run test:e2e                              # Staging
 *
 * `docs/operations/release-gate.md` says what each run is allowed to prove.
 */

const stagingUrl = process.env.LIYAN_E2E_BASE_URL;
// localhost, not 127.0.0.1: Vite binds to the name, and on a machine where it
// resolves to ::1 first a check against the IPv4 address never answers.
const workbenchUrl = stagingUrl ?? "http://localhost:5199";
const apiUrl = process.env.LIYAN_E2E_API_URL ?? "http://127.0.0.1:8099";

export default defineConfig({
  testDir: "./e2e",
  // 知言 and 立言 are provider-paced even against doubles, and the workbench
  // polls rather than subscribes, so the waits here are real waits.
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  // A Staging run creates real data with real money behind it; a retry that
  // silently passes on the second attempt hides exactly what the gate is for.
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: workbenchUrl,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    locale: "zh-CN",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: stagingUrl
    ? undefined
    : [
        {
          command: "../../.venv/bin/python ../../scripts/e2e_server.py --port 8099",
          url: `${apiUrl}/health/live`,
          reuseExistingServer: !process.env.CI,
          timeout: 120_000,
        },
        {
          // `--mode e2e` loads `.env.e2e` from the repo root, which is where
          // the workbench's own configuration for this run lives. Passing it
          // through `env:` here would not work: Vite's env files win over the
          // process environment, so a developer's `.env` would decide.
          command: "npm run dev -- --mode e2e --port 5199 --strictPort",
          url: workbenchUrl,
          reuseExistingServer: !process.env.CI,
          timeout: 120_000,
        },
      ],
});
