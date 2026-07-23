import { test, expect, type Page } from '@playwright/test';

// ADR 0009 stream 9-S2c: the top-bar GraphPicker wired onto the merged 8-S1
// sync store. What must hold (D6 + the ADR 0008 composition point):
//  * switching entries moves `?graph=<id>` in the URL — the store's `graphId`
//    key, not a picker-owned cache;
//  * the canvas fully swaps (new node types render, the old ones are gone);
//  * per-entry panels (run results) are cleared on switch;
//  * the store still drives edits on the newly selected entry — a widget
//    commit PUTs the SCOPED route (`/api/graphs/{id}/graph`), not the
//    unscoped alias;
//  * the branch badge (checkout-global, not per-entry) is unchanged by a switch;
//  * everything serves from localhost — EXTERNAL_REQUESTS must stay 0.

function nodeCard(page: Page, title: string) {
  return page
    .locator('[data-testid="spec-node"]')
    .filter({ has: page.locator('[data-testid="node-title"]', { hasText: new RegExp(`^${title}$`) }) })
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

test('switches entries via the picker: URL key, full canvas swap, cleared run panel, scoped store writes', async ({
  page,
}) => {
  const external = trackExternalRequests(page);

  await page.goto('/');
  await expect(page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]')).toBeVisible({
    timeout: 15_000,
  });

  // The picker is visible (the demo catalog has several entries) and starts on
  // the server's default (showcase).
  const picker = page.getByTestId('graph-picker');
  await expect(picker).toBeVisible();
  const button = page.getByTestId('graph-picker-button');
  await expect(button).toContainText('Showcase');

  // Showcase-specific nodes are on the canvas; capacity_check's are not.
  await expect(nodeCard(page, 'parse_expr')).toBeVisible();
  await expect(nodeCard(page, 'check_capacity')).toHaveCount(0);

  const badgeBefore = await page.getByTestId('branch-badge').textContent();

  // Produce a run so its panel exists before the switch.
  const runResponse = page.waitForResponse((r) => r.url().includes('/api/run') && r.status() === 200);
  await page.getByTestId('run-button').click();
  await runResponse;
  await expect(page.getByTestId('run-results')).toBeVisible();

  // --- switch: showcase -> capacity_check via the picker -----------------
  await button.click();
  await expect(page.getByTestId('graph-picker-menu')).toBeVisible();
  const graphResponse = page.waitForResponse(
    (r) => r.url().includes('/api/graphs/capacity_check/graph') && r.status() === 200,
  );
  await page.getByTestId('graph-picker-option-capacity_check').click();
  await graphResponse;

  // Selection lives in the URL (ADR 0009 D6) — the store reacts to the key.
  await expect(page).toHaveURL(/[?&]graph=capacity_check(&|$)/);

  // Full canvas swap: capacity_check's nodes render, showcase's are gone.
  await expect(page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]')).toBeVisible({
    timeout: 15_000,
  });
  await expect(nodeCard(page, 'check_capacity')).toBeVisible();
  await expect(nodeCard(page, 'select_extreme').first()).toBeVisible();
  await expect(nodeCard(page, 'parse_expr')).toHaveCount(0);

  // Run/export panels are per-entry and meaningless across a switch (D6).
  await expect(page.getByTestId('run-results')).toHaveCount(0);

  // Branch badge is checkout-global — unaffected by which entry is viewed.
  await expect(page.getByTestId('branch-badge')).toHaveText(badgeBefore ?? '');

  // The picker button now names the new entry.
  await expect(button).toContainText('Capacity check');

  // --- the 8-S1 store still drives edits on the NEW entry ----------------
  // A literal string input (`forces_path`, wired as `read_table`'s `path`)
  // renders a plain text chip (DefaultEditor). Committing it must PUT the
  // entry-SCOPED route, proving the write queue reads the switched `graphId`
  // out of the store rather than a stale/unscoped one. The PUT is mocked (as
  // in tests/widgets.spec.ts) so this stays parallel-safe against the shared
  // demo server instead of rewriting the real capacity_check source file.
  const original = await (await page.request.get('/api/graphs/capacity_check/graph')).json();
  const edited = JSON.parse(JSON.stringify(original));
  const NEW_PATH = 'forces-edited.csv';
  for (const node of edited.nodes) {
    if (node.type === 'table.read_table') node.inputs.path = NEW_PATH;
  }
  const scopedPutPath = '**/api/graphs/capacity_check/graph';
  await page.route(scopedPutPath, async (route) => {
    if (route.request().method() === 'PUT') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ graph: edited }) });
    }
    return route.continue();
  });

  // Scope to the `path` input's own row (not `.first()`) — `read_table` has
  // two literal inputs (`path`, `text`) and committing collapses the edited
  // one from a chip into an open `widget-slot`, which would otherwise shift
  // what `.first()` resolves to.
  const card = nodeCard(page, 'read_table').first();
  const pathRow = card
    .locator('.ge-socket--in')
    .filter({ has: page.locator('.ge-socket__name', { hasText: 'path' }) });
  await pathRow.getByTestId('widget-chip').click();
  const input = pathRow.getByTestId('widget-editor-text');
  await expect(input).toBeVisible();

  const scopedPut = page.waitForResponse(
    (r) => r.url().includes('/api/graphs/capacity_check/graph') && r.request().method() === 'PUT',
  );
  await input.fill(NEW_PATH);
  await input.press('Enter');
  await scopedPut;
  await pathRow.getByTestId('widget-done').click(); // back to a closed chip
  await expect(pathRow.getByTestId('widget-chip')).toContainText(NEW_PATH);

  await page.screenshot({ path: 'tests/__screenshots__/graph-picker.png', fullPage: false });

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});
