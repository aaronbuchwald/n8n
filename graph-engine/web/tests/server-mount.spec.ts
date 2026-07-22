import { test, expect } from '@playwright/test';

// The showcase demo (ADR 0005): a few stable node titles from both chains.
const NODE_TITLES = ['read_table', 'apply_recipe', 'parse_expr', 'dashboard'];
const NODE_COUNT = 12;

// This spec loads the app from the FastAPI STATIC MOUNT at "/" (baseURL points
// at the uvicorn port, not vite preview). It proves the built bundle works when
// served same-origin with /api/* straight from the Python server — the exact
// path a user hits after `pnpm build` + `python -m server --demo` + Enter.
test('serves a working app from the FastAPI static mount at "/"', async ({ page }) => {
  const consoleErrors: string[] = [];
  const badResponses: string[] = [];
  page.on('console', (m) => {
    if (m.type() === 'error') consoleErrors.push(m.text());
  });
  page.on('pageerror', (e) => consoleErrors.push(`pageerror: ${e.message}`));
  page.on('response', (r) => {
    if (r.status() >= 400) badResponses.push(`HTTP ${r.status()} ${r.url()}`);
  });

  // Both API endpoints must be fetched SAME-ORIGIN (same port as the page) and
  // return 200 before the canvas populates — no proxy, no second origin.
  const specsResponse = page.waitForResponse(
    (r) => r.url().includes('/api/specs') && r.status() === 200,
  );
  const graphResponse = page.waitForResponse(
    (r) => r.url().includes('/api/graph') && r.status() === 200,
  );

  await page.goto('/');
  const specs = await specsResponse;
  const graph = await graphResponse;

  // Same-origin proof: the /api/* calls share the page's origin.
  const pageOrigin = new URL(page.url()).origin;
  expect(new URL(specs.url()).origin).toBe(pageOrigin);
  expect(new URL(graph.url()).origin).toBe(pageOrigin);

  // The four live node titles render.
  const canvas = page.getByTestId('flow-canvas');
  await expect(canvas).toBeVisible();
  for (const title of NODE_TITLES) {
    await expect(
      page.locator('[data-testid="node-title"]', { hasText: new RegExp(`^${title}$`) }),
    ).toBeVisible();
  }
  await expect(page.getByTestId('spec-node')).toHaveCount(NODE_COUNT);
  await expect(page.getByTestId('output-badge')).toBeVisible();

  await page.screenshot({ path: 'tests/__screenshots__/server-mount.png', fullPage: false });

  // No hashed-asset 404s (a wrong Vite base would surface here) and a clean
  // console — the whole point of serving from the server root working.
  expect(badResponses, `unexpected failed responses: ${badResponses.join(', ')}`).toEqual([]);
  expect(consoleErrors, `console errors: ${consoleErrors.join(', ')}`).toEqual([]);
});
