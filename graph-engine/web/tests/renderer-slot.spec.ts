import { test, expect, type Page } from '@playwright/test';

import { stableScreenshot, stubWorkspace } from './visual';

// Pin the branch label the top bar paints, so the committed captures don't
// depend on which branch/worktree the suite happens to run from.
test.beforeEach(async ({ page }) => {
  await stubWorkspace(page);
});

// ADR 0010 stream 10-W: the renderer registry + RendererSlot shell, WITHOUT any
// product kind (html-card is 10-K). What must hold:
//  * nodes with no declared renderer show today's result chips, unchanged;
//  * a spec declaring an UNKNOWN kind degrades to the same chips (D4 fallback);
//  * a declared, registered kind mounts in the result strip only — header,
//    sockets, handles and widget slots stay shell-owned (D3);
//  * the results panel resolves the SAME registry for the output node (D7).
//
// Since 10-K the packs DO declare `html-card` (sym/table/showcase), so these
// slot-semantics tests rewrite `/api/specs` in-flight to strip every declared
// renderer and attach only the bundled `dev-json` seam-proof kind where a test
// needs one — restoring the world each fallback rule describes. The `html-card`
// kind itself is covered in html-card.spec.ts. The UI still renders everything
// from live HTTP responses, all served from localhost (EXTERNAL_REQUESTS must
// stay 0).

function nodeCard(page: Page, title: string) {
  return page
    .locator('[data-testid="spec-node"]')
    .filter({
      has: page.locator('[data-testid="node-title"]', { hasText: new RegExp(`^${title}$`) }),
    })
    .first();
}

/** Collect requests leaving localhost; the offline posture requires none. */
function trackExternalRequests(page: Page): string[] {
  const external: string[] = [];
  page.on('request', (req) => {
    const { hostname } = new URL(req.url());
    if (hostname !== '127.0.0.1' && hostname !== 'localhost') external.push(req.url());
  });
  return external;
}

/**
 * Rewrite /api/specs in flight: strip EVERY declared renderer, then attach
 * `renderer: {kind}` per `overrides` entry (keyed by spec title).
 */
async function overrideRenderers(page: Page, overrides: Record<string, string>): Promise<void> {
  await page.route('**/api/specs', async (route) => {
    const response = await route.fetch();
    const body = (await response.json()) as {
      specs: Record<string, { title: string; renderer?: { kind: string } | null }>;
    };
    for (const spec of Object.values(body.specs)) {
      const kind = overrides[spec.title];
      spec.renderer = kind ? { kind } : null;
    }
    await route.fulfill({ response, json: body });
  });
}

async function runGraph(page: Page): Promise<void> {
  const runResponse = page.waitForResponse(
    (r) => r.url().includes('/api/run') && r.status() === 200,
  );
  await page.getByTestId('run-button').click();
  await runResponse;
}

test('nodes without a declared renderer keep the result-chips fallback', async ({ page }) => {
  const external = trackExternalRequests(page);
  await overrideRenderers(page, {});
  await page.goto('/');
  await expect(page.getByTestId('flow-canvas')).toBeVisible();

  // With every declaration stripped, no spec declares `renderer` → no surfaces.
  await expect(page.getByTestId('render-surface')).toHaveCount(0);

  await runGraph(page);

  // Every executed node shows today's chips footer; still zero surfaces.
  await expect(nodeCard(page, 'parse_expr').getByTestId('node-result')).toBeVisible();
  await expect(nodeCard(page, 'dashboard').getByTestId('node-result')).toBeVisible();
  await expect(page.getByTestId('render-surface')).toHaveCount(0);

  // The panel's no-renderer fallback: the sandboxed output iframe, unchanged.
  await expect(page.getByTestId('run-result-frame')).toHaveAttribute('sandbox', '');

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});

test('an unknown renderer kind degrades to the same chips (open-vocabulary fallback)', async ({
  page,
}) => {
  const external = trackExternalRequests(page);
  await overrideRenderers(page, { parse_expr: 'kind-this-bundle-does-not-ship' });
  await page.goto('/');
  await expect(page.getByTestId('flow-canvas')).toBeVisible();

  // Unknown kind → rendererFor resolves null → no surface mounts.
  await expect(page.getByTestId('render-surface')).toHaveCount(0);

  await runGraph(page);
  await expect(nodeCard(page, 'parse_expr').getByTestId('node-result')).toBeVisible();
  await expect(page.getByTestId('render-surface')).toHaveCount(0);

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});

test('a registered kind mounts in the result strip only; shell chrome is untouched', async ({
  page,
}) => {
  const external = trackExternalRequests(page);
  await overrideRenderers(page, { parse_expr: 'dev-json' });
  await page.goto('/');
  await expect(page.getByTestId('flow-canvas')).toBeVisible();

  const card = nodeCard(page, 'parse_expr');

  // Declared + registered → the surface mounts BEFORE any run (result: null);
  // the seam-proof kind shows its placeholder. Only this node has a surface.
  await expect(card.getByTestId('render-surface')).toBeVisible();
  await expect(page.getByTestId('render-surface')).toHaveCount(1);
  const renderer = card.getByTestId('dev-json-renderer');
  await expect(renderer).toHaveAttribute('data-renderer-surface', 'card');
  await expect(renderer).toContainText('run to render');

  // Shell chrome stays shell-owned (ADR 0010 D3): header, sockets + handles,
  // and the ADR 0005 widget slot all still render on the same card.
  await expect(card.getByTestId('node-title')).toHaveText('parse_expr');
  await expect(card.locator('.ge-socket__name', { hasText: 'text' })).toBeVisible();
  await expect(card.locator('.ge-handle--in').first()).toBeAttached();
  await expect(card.locator('.ge-handle--out').first()).toBeAttached();
  await expect(card.getByTestId('widget-preview').first()).toBeVisible();

  await runGraph(page);

  // After the run the renderer shows the node's socket values in the strip
  // (the engine's default output socket is named "result"); undeclared nodes
  // still show plain chips next to it.
  await expect(renderer).toContainText('result');
  await expect(nodeCard(page, 'dashboard').getByTestId('node-result')).toBeVisible();

  await stableScreenshot(page, 'tests/__screenshots__/renderer-slot.png');

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});

test('the results panel resolves the same registry for the output node (D7)', async ({ page }) => {
  const external = trackExternalRequests(page);
  await overrideRenderers(page, { dashboard: 'dev-json' });
  await page.goto('/');
  await expect(page.getByTestId('flow-canvas')).toBeVisible();

  await runGraph(page);

  // The output node declares dev-json → the panel mounts it with
  // surface="panel" instead of the string-iframe special case…
  const results = page.getByTestId('run-results');
  const panelRenderer = results.getByTestId('dev-json-renderer');
  await expect(panelRenderer).toHaveAttribute('data-renderer-surface', 'panel');
  await expect(panelRenderer).toContainText('result');
  await expect(page.getByTestId('run-result-frame')).toHaveCount(0);

  // …while the same node's CARD mounts the same component with surface="card".
  const cardRenderer = nodeCard(page, 'dashboard').getByTestId('dev-json-renderer');
  await expect(cardRenderer).toHaveAttribute('data-renderer-surface', 'card');

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});
