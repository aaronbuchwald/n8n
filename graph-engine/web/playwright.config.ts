import { defineConfig, devices } from '@playwright/test';
import { existsSync } from 'node:fs';

// Chromium is pre-installed in this environment; do NOT run `playwright install`.
// If the pinned browser is absent we point executablePath at the pre-installed one.
const PREINSTALLED_CHROMIUM = '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';
const executablePath = existsSync(PREINSTALLED_CHROMIUM) ? PREINSTALLED_CHROMIUM : undefined;

// Overridable so two checkouts (or two agents) on one box don't fight over the
// same two ports. Defaults are unchanged.
const WEB_PORT = Number(process.env.GE_WEB_PORT ?? 4173);
const API_PORT = Number(process.env.GE_API_PORT ?? 8000);

export default defineConfig({
  testDir: './tests',
  // The server-mount spec has its own config (playwright.server-mount.config.ts)
  // that boots uvicorn as the origin; it must not run against vite preview here.
  testIgnore: /server-mount\.spec\.ts/,
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
      testIgnore: [
        /server-mount\.spec\.ts/,
        /canvas-editing\.spec\.ts/,
        /calc-widget\.spec\.ts/,
        /formula-editing\.spec\.ts/,
        // Real showcase-workspace mutators — serialized into the chain below so
        // they never race the parallel pack (or each other) on showcase.py.
        /new-node-authoring\.spec\.ts/,
        /node-catalog\.spec\.ts/,
      ],
    },
    {
      // Canvas structural editing (ADR 0011 11-W4) mutates the demo module,
      // its layout sidecar, and asserts byte-level .py stability — it must own
      // the workspace alone. Serial within the file; sequenced after the
      // parallel pack (ADR 0017 W4 retired the old `palette` project it used to
      // follow). Run alone with: --project=editing --no-deps
      name: 'editing',
      use: { ...devices['Desktop Chrome'] },
      testMatch: /canvas-editing\.spec\.ts/,
      dependencies: ['chromium'],
    },
    {
      // The calc widget (ADR 0007 W) commits equations against handcalc_demo,
      // REALLY rewriting its module and restoring it afterwards — it must own
      // the workspace alone too. Run alone with: --project=calc --no-deps
      name: 'calc',
      use: { ...devices['Desktop Chrome'] },
      testMatch: /calc-widget\.spec\.ts/,
      dependencies: ['editing'],
    },
    {
      // Formula editing (ADR 0018) commits `sheet.calc_card` literals against
      // capacity_check, REALLY rewriting its module and restoring it afterwards
      // — same exclusive-workspace rule as `calc`, on a different example, so
      // it gets its own link in the chain. Run alone with:
      // --project=formula --no-deps
      name: 'formula',
      use: { ...devices['Desktop Chrome'] },
      testMatch: /formula-editing\.spec\.ts/,
      dependencies: ['calc'],
    },
    {
      // New-node authoring REALLY writes new @node functions into showcase.py
      // and restores them; its create/collision tests must not race each other
      // or any other showcase mutator. Serial, sequenced after the pack.
      name: 'new-node',
      use: { ...devices['Desktop Chrome'] },
      testMatch: /new-node-authoring\.spec\.ts/,
      dependencies: ['formula'],
    },
    {
      // The node catalog's destructive tests (click-insert, multi-add, drag)
      // REALLY mutate the showcase graph (→ showcase.py writeback) and restore
      // it — they must own the workspace alone too (ADR 0017). Run alone with:
      // --project=catalog --no-deps
      name: 'catalog',
      use: { ...devices['Desktop Chrome'] },
      testMatch: /node-catalog\.spec\.ts/,
      dependencies: ['new-node'],
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
      command: `uv run --extra sym --extra server python -m server --demo --host 127.0.0.1 --port ${API_PORT}`,
      cwd: '..',
      url: `http://127.0.0.1:${API_PORT}/api/specs`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: `pnpm build && pnpm exec vite preview --port ${WEB_PORT} --strictPort`,
      // The bundle is served same-origin with /api via vite's preview proxy;
      // point that proxy at whichever API port this run booted.
      env: { GE_API_TARGET: `http://127.0.0.1:${API_PORT}` },
      url: `http://127.0.0.1:${WEB_PORT}`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
