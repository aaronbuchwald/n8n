import { defineConfig, devices } from '@playwright/test';
import { existsSync } from 'node:fs';

// Chromium is pre-installed in this environment; do NOT run `playwright install`.
// If the pinned browser is absent we point executablePath at the pre-installed one.
const PREINSTALLED_CHROMIUM = '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';
const executablePath = existsSync(PREINSTALLED_CHROMIUM) ? PREINSTALLED_CHROMIUM : undefined;

const WEB_PORT = 4173;
const API_PORT = 8000;

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  reporter: [['list']],
  timeout: 60_000,
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: 'off',
    launchOptions: executablePath ? { executablePath } : {},
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  // Boot the LIVE stack the app renders from:
  //  1. the FastAPI server with the minimal demo loaded (specs + sample graph),
  //  2. the built web bundle via `vite preview`, whose `/api` proxy forwards to
  //     the server (see vite.config.ts). This proves the render comes from the
  //     server over HTTP, not baked-in fixtures.
  webServer: [
    {
      // `cwd` is relative to this config's directory (web/) → the graph-engine root.
      command: `uv run --extra server python -m server --demo --host 127.0.0.1 --port ${API_PORT}`,
      cwd: '..',
      url: `http://127.0.0.1:${API_PORT}/api/specs`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: 'pnpm build && pnpm preview',
      url: `http://127.0.0.1:${WEB_PORT}`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
