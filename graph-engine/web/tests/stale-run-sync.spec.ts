import { test, expect, type Page } from '@playwright/test';

// ADR 0008 Phase 0 (stream 8-P0): the immediate stale-UI fix. The reported bug
// was that after an edit the run-derived values (node result chips, run-results
// value lines) kept showing what the PRE-edit code computed — the views never
// invalidated. This proves the fix end-to-end against the live demo stack:
//   * run the graph → result chips + run-results panel appear, NOT stale;
//   * edit a node's literal (widget commit) → the last run's values are marked
//     stale: a "results from before your edit" banner appears with a one-click
//     "Run again", and both the canvas chips and the results panel carry
//     data-run-stale="true" (the CSS dims them);
//   * "Run again" re-executes and clears the stale state.
//
// The COMMIT (PUT /api/graph) is mocked so this stays parallel-safe against the
// shared demo server without mutating it; /api/run is the real, read-only engine.

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

// Where the click-through screenshot lands (overridable so CI can redirect it).
const SCREENSHOT_PATH = process.env.STALE_RUN_SCREENSHOT ?? 'test-results/stale-run-banner.png';

test('an edit marks the previous run stale (dimmed + banner) and Run again clears it', async ({
  page,
}) => {
  await gotoAndSettle(page);

  // 1. Run the real engine; the results surfaces appear and are NOT stale yet.
  const firstRun = page.waitForResponse((r) => r.url().includes('/api/run') && r.status() === 200);
  await page.getByTestId('run-button').click();
  await firstRun;

  const results = page.getByTestId('run-results');
  await expect(results).toBeVisible();
  await expect(page.getByTestId('node-result').first()).toBeVisible();
  await expect(page.getByTestId('run-stale-banner')).toHaveCount(0);
  await expect(page.getByTestId('flow-canvas')).not.toHaveAttribute('data-run-stale', 'true');
  await expect(results).not.toHaveAttribute('data-run-stale', 'true');

  // 2. Edit a node literal. Mock only the PUT so the commit response carries the
  //    re-served graph (the Phase-0 contract: the shell ingests it directly,
  //    with no post-commit reload).
  const original = await (await page.request.get('/api/graph')).json();
  const edited = JSON.parse(JSON.stringify(original));
  const NEW_EXPR = 'x**3 - 1';
  for (const node of edited.nodes) {
    if (node.type === 'sym.parse_expr') node.inputs.text = NEW_EXPR;
  }
  await page.route('**/api/graph', async (route) => {
    if (route.request().method() === 'PUT') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ graph: edited }),
      });
    }
    return route.continue();
  });

  const card = nodeCard(page, 'parse_expr');
  await card.getByTestId('widget-chip').first().click();
  const input = page.getByTestId('widget-editor-math-input');
  await expect(input).toBeVisible();
  await input.fill(NEW_EXPR);
  const put = page.waitForResponse(
    (r) => r.url().includes('/api/graph') && r.request().method() === 'PUT',
  );
  await input.press('Enter');
  await put;

  // 3. The previous run is now stale: banner with a one-click re-run, and both
  //    the canvas chips and the results panel are flagged for dimming.
  const banner = page.getByTestId('run-stale-banner');
  await expect(banner).toBeVisible();
  await expect(banner).toContainText('before your edit');
  const rerun = page.getByTestId('run-stale-rerun');
  await expect(rerun).toBeEnabled();
  await expect(page.getByTestId('flow-canvas')).toHaveAttribute('data-run-stale', 'true');
  await expect(results).toHaveAttribute('data-run-stale', 'true');
  // The dim is actually applied (CSS keyed on the ancestor attribute).
  await expect(page.getByTestId('node-result').first()).toHaveCSS('opacity', '0.45');

  await page.screenshot({ path: SCREENSHOT_PATH, fullPage: true });

  // 4. Run again re-executes and clears the stale state.
  const secondRun = page.waitForResponse((r) => r.url().includes('/api/run') && r.status() === 200);
  await rerun.click();
  await secondRun;
  await expect(page.getByTestId('run-stale-banner')).toHaveCount(0);
  await expect(page.getByTestId('flow-canvas')).not.toHaveAttribute('data-run-stale', 'true');
});
