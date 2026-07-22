import { defineConfig, devices } from '@playwright/test';
import { existsSync } from 'node:fs';

// Chromium is pre-installed in this environment; do NOT run `playwright install`.
const PREINSTALLED_CHROMIUM = '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';
const executablePath = existsSync(PREINSTALLED_CHROMIUM) ? PREINSTALLED_CHROMIUM : undefined;

// A dedicated port so this config never clashes with the vite-preview stack.
const SERVER_PORT = 8123;

// This config proves the built bundle works when served DIRECTLY from the
// FastAPI static mount at "/" (same-origin with /api/*) — no vite preview, no
// proxy. `pnpm build` runs first so web/dist exists before uvicorn boots and
// mounts it; if the two were racing, uvicorn would serve the build hint instead.
export default defineConfig({
  testDir: './tests',
  testMatch: /server-mount\.spec\.ts/,
  fullyParallel: false,
  reporter: [['list']],
  timeout: 60_000,
  use: {
    baseURL: `http://127.0.0.1:${SERVER_PORT}`,
    trace: 'off',
    launchOptions: executablePath ? { executablePath } : {},
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      // Build the bundle in web/, THEN boot uvicorn from the graph-engine root
      // so the static mount picks up the freshly built web/dist. Single chained
      // command so the build is guaranteed to finish before uvicorn starts.
      // `cwd` is the graph-engine root (relative to this config's dir, web/).
      command: `cd web && pnpm build && cd .. && uv run --extra sym --extra server python -m server --demo --host 127.0.0.1 --port ${SERVER_PORT} --no-open`,
      cwd: '..',
      url: `http://127.0.0.1:${SERVER_PORT}/api/specs`,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
    },
  ],
});
