import { test, expect, type Page } from '@playwright/test';

// ADR 0008 Phase 1 (8-S1), Gap G6 + Open confirmation 7: a write that changes a
// node's SHAPE (its socket signature) must re-measure/re-layout that node — not
// just patch its data in place. The store's structure key now carries a per-node
// socket signature, so a source save that alters the signature flows through the
// store (ingestSourceSave → new spec) and re-seeds the layout, while a plain
// literal edit (same signature) still patches in place with no re-frame.
//
// The SAVE (PUT /api/source) is mocked to add one output socket, so this stays
// parallel-safe against the shared demo server without mutating real files.

function nodeCard(page: Page, title: string) {
  return page
    .locator('[data-testid="spec-node"]')
    .filter({
      has: page.locator('[data-testid="node-title"]', { hasText: new RegExp(`^${title}$`) }),
    })
    .first();
}

async function gotoAndSettle(page: Page) {
  await page.goto('/');
  await expect(page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]')).toBeVisible({
    timeout: 15_000,
  });
}

const SCREENSHOT_PATH = process.env.SHAPE_RELAYOUT_SCREENSHOT ?? 'test-results/shape-relayout.png';

test('a shape-changing source save re-lays-out the card via the store (G6)', async ({ page }) => {
  await gotoAndSettle(page);

  const specId = 'sym.parse_expr';
  // Build the mocked save response: the real source + spec, with one EXTRA
  // output socket (the shape change) and the re-projected graph the server now
  // serves (ADR 0008 "writes return truth" — the store ingests all of it).
  const specsBody = await (await page.request.get('/api/specs')).json();
  const spec = specsBody.specs[specId];
  const source = await (await page.request.get(`/api/source/${specId}`)).json();
  const graph = await (await page.request.get('/api/graph')).json();
  const saveResult = {
    ...source,
    spec: { ...spec, outputs: [...spec.outputs, { name: 'shape_probe', type: 'int' }] },
    graph,
    graphErrors: [],
  };
  await page.route(`**/api/source/${specId}`, async (route) => {
    if (route.request().method() === 'PUT') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(saveResult),
      });
    }
    return route.continue();
  });

  // Open the node's inspector → source editor, then save.
  const card = nodeCard(page, 'parse_expr');
  await card.getByTestId('node-title').click();
  await expect(page.getByTestId('node-inspector')).toBeVisible();
  await page.getByTestId('inspector-open-definition').click();
  await expect(page.getByTestId('source-editor')).toBeVisible();
  await expect(page.getByTestId('source-save-button')).toBeEnabled();
  await page.getByTestId('source-save-button').click();

  // The store ingested the new spec: the inspector's outputs (derived from the
  // store, not a private fetch) now list the added socket.
  await page.getByTestId('source-back').click();
  await expect(page.getByTestId('inspector-outputs')).toContainText('shape_probe');

  // Close the inspector; the CARD itself now carries the new socket row — the
  // shape change reached the canvas (not just the panel) and the layout stayed
  // coherent (re-measured, still framed and ready — G6, no stale geometry).
  await page.getByTestId('dock-tab-close-inspector').click();
  await expect(card.getByText('shape_probe')).toBeVisible();
  await expect(
    page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]'),
  ).toBeVisible();

  await page.screenshot({ path: SCREENSHOT_PATH, fullPage: true });
});
