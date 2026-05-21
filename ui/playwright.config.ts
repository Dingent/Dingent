import { defineConfig, devices } from "@playwright/test";

const backendPort = Number(process.env.E2E_BACKEND_PORT ?? 8765);
const frontendPort = Number(process.env.E2E_FRONTEND_PORT ?? 3100);
const backendURL = `http://127.0.0.1:${backendPort}`;
const frontendURL = `http://127.0.0.1:${frontendPort}`;

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: {
    timeout: 15_000,
  },
  use: {
    baseURL: `${frontendURL}/dingent/web`,
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: `DATABASE_URL=sqlite:///./.playwright-e2e.db E2E_BACKEND_PORT=${backendPort} uv run python tests/e2e/playwright_server.py`,
      cwd: "..",
      url: `${backendURL}/api/v1/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `BACKEND_URL=${backendURL} API_BASE_URL=${backendURL}/api/v1 bun run build && mkdir -p .next/standalone/.next && cp -R .next/static .next/standalone/.next/static && BACKEND_URL=${backendURL} API_BASE_URL=${backendURL}/api/v1 HOSTNAME=127.0.0.1 PORT=${frontendPort} node .next/standalone/server.js`,
      url: `${frontendURL}/dingent/web`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], channel: "chromium" },
    },
  ],
});
