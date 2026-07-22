import { defineConfig, devices } from '@playwright/test';
import { existsSync } from 'node:fs';

// Chromium is pre-installed in this environment; do NOT run `playwright install`.
// If the pinned browser is absent we point executablePath at the pre-installed one.
const PREINSTALLED_CHROMIUM = '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';
const executablePath = existsSync(PREINSTALLED_CHROMIUM) ? PREINSTALLED_CHROMIUM : undefined;

const PORT = 4173;

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  reporter: [['list']],
  timeout: 60_000,
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: 'off',
    launchOptions: executablePath ? { executablePath } : {},
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  // Build then serve the production bundle offline; proves the bundle is
  // fully self-contained (no CDN, no dev server).
  webServer: {
    command: 'pnpm build && pnpm preview',
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
