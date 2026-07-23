import { test, expect, type Page } from '@playwright/test';

// ADR 0013 Change 1 — all widget editing moved off the node card into the
// inspector; the card is a read-only face (previews + sockets). These specs run
// against the served showcase graph (`/`) and cover the acceptance criteria:
//   * 1.1 no editable control on any card (no input/textarea/select/CE, no
//     widget-chip/widget-slot anywhere);
//   * 1.2 node click → inspector with an `inspector-widget-slot` per widget input;
//   * 1.3 each kind editable ONLY in the inspector — the card preview and the
//     committed graph reflect the edit (text/number/math/table here; calc lives
//     in calc-widget.spec.ts against capacity_check);
//   * 1.4 the card shows read-only previews + wireable sockets;
//   * 1.8 clicking anywhere on a card (previews included) selects it; Escape closes.
//
// COMMIT path (PUT /api/graph) is mocked so this stays parallel-safe against the
// shared demo server without mutating it — the PUT is echoed back (the store
// ingests exactly what it committed) and GET stays live. Disk persistence is
// proven by the Python round-trip test. checkbox has no widget in any served
// demo graph, so its E2E assertion is deferred; it shares the identical
// InspectorWidgetSlot mount + commit path and is covered by the store specs.

function nodeCard(page: Page, title: string) {
  return page
    .locator('[data-testid="spec-node"]')
    .filter({ has: page.locator('[data-testid="node-title"]', { hasText: new RegExp(`^${title}$`) }) })
    .first();
}

async function settle(page: Page) {
  await page.goto('/');
  await expect(page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]')).toBeVisible({
    timeout: 15_000,
  });
}

async function openInspector(page: Page, title: string) {
  await nodeCard(page, title).getByTestId('node-title').click();
  const inspector = page.getByTestId('node-inspector');
  await expect(inspector).toBeVisible();
  return inspector;
}

interface Committed {
  last: { nodes: Array<{ id: string; type: string; inputs: Record<string, unknown> }> } | null;
}

/** Echo PUTs back (the store ingests what it committed) and capture the graph. */
async function mockCommits(page: Page): Promise<Committed> {
  const state: Committed = { last: null };
  await page.route('**/api/graph', async (route) => {
    const req = route.request();
    if (req.method() === 'PUT') {
      const body = req.postDataJSON() as { graph: Committed['last'] };
      state.last = body.graph;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ graph: body.graph }),
      });
    }
    return route.continue();
  });
  return state;
}

const waitForPut = (page: Page) =>
  page.waitForResponse(
    (r) => new URL(r.url()).pathname === '/api/graph' && r.request().method() === 'PUT',
  );

function nodeInputs(committed: Committed, type: string): Record<string, unknown> | undefined {
  return committed.last?.nodes.find((n) => n.type === type)?.inputs;
}

test('1.1 no editable control renders on any node card', async ({ page }) => {
  await settle(page);
  expect(await page.getByTestId('spec-node').count()).toBeGreaterThan(0);
  // No editors on the cards…
  await expect(
    page.locator(
      '[data-testid="spec-node"] input, [data-testid="spec-node"] textarea, [data-testid="spec-node"] select, [data-testid="spec-node"] [contenteditable="true"]',
    ),
  ).toHaveCount(0);
  // …and the removed canvas-editing testids match nothing, anywhere.
  await expect(page.getByTestId('widget-chip')).toHaveCount(0);
  await expect(page.getByTestId('widget-slot')).toHaveCount(0);
  await expect(page.getByTestId('widget-done')).toHaveCount(0);
});

test('1.2 clicking a node opens the inspector with an editor slot per widget input', async ({
  page,
}) => {
  await settle(page);
  const inspector = await openInspector(page, 'read_table');
  await expect(
    inspector.locator('[data-testid="inspector-widget-slot"][data-input="path"]'),
  ).toBeVisible();
  await expect(inspector.getByTestId('inspector-widget-slot').first()).toBeVisible();
});

test('1.3/1.4 text: editable only in the inspector; card preview + graph reflect the commit', async ({
  page,
}) => {
  const committed = await mockCommits(page);
  await settle(page);
  const card = nodeCard(page, 'read_table');
  // No text editor on the card — only a read-only preview.
  await expect(card.getByTestId('widget-editor-text')).toHaveCount(0);
  await expect(card.getByTestId('widget-preview').first()).toBeVisible();

  const inspector = await openInspector(page, 'read_table');
  const input = inspector
    .locator('[data-testid="inspector-widget-slot"][data-input="path"]')
    .getByTestId('widget-editor-text');
  await expect(input).toBeVisible();

  const NEW = 'edited-showcase.csv';
  const put = waitForPut(page);
  await input.fill(NEW);
  await input.press('Enter');
  await put;

  expect(nodeInputs(committed, 'table.read_table')?.path).toBe(NEW);
  const pathRow = card
    .locator('.ge-socket--in')
    .filter({ has: page.locator('.ge-socket__name', { hasText: 'path' }) });
  await expect(pathRow.getByTestId('widget-preview')).toContainText(NEW);
});

test('1.3 number: editable only in the inspector; card preview + graph reflect the commit', async ({
  page,
}) => {
  const committed = await mockCommits(page);
  await settle(page);
  const card = nodeCard(page, 'pick');
  await expect(card.getByTestId('widget-editor-number')).toHaveCount(0);

  const inspector = await openInspector(page, 'pick');
  const input = inspector
    .locator('[data-testid="inspector-widget-slot"][data-input="index"]')
    .getByTestId('widget-editor-number');
  await expect(input).toBeVisible();

  const put = waitForPut(page);
  await input.fill('1');
  await input.press('Enter');
  await put;

  expect(nodeInputs(committed, 'sym.pick')?.index).toBe(1);
  const indexRow = card
    .locator('.ge-socket--in')
    .filter({ has: page.locator('.ge-socket__name', { hasText: 'index' }) });
  await expect(indexRow.getByTestId('widget-preview')).toContainText('1');
});

test('1.3/1.4 math: editable only in the inspector; the card block preview re-typesets', async ({
  page,
}) => {
  const committed = await mockCommits(page);
  await settle(page);
  const card = nodeCard(page, 'parse_expr');
  // The card shows a read-only typeset block preview, no editor.
  const blockPreview = card.locator('[data-testid="widget-preview"][data-kind="math"]');
  await expect(blockPreview).toBeVisible();
  await expect(blockPreview.locator('.katex').first()).toBeVisible({ timeout: 8_000 });
  await expect(card.getByTestId('widget-editor-math-input')).toHaveCount(0);

  const inspector = await openInspector(page, 'parse_expr');
  const input = inspector.getByTestId('widget-editor-math-input');
  await expect(input).toBeVisible();

  const NEW = 'x**3 - 1';
  const put = waitForPut(page);
  await input.fill(NEW);
  await input.press('Enter');
  await put;

  expect(nodeInputs(committed, 'sym.parse_expr')?.text).toBe(NEW);
  // The card's block preview re-typesets from the committed literal.
  await expect(blockPreview.locator('.katex').first()).toBeVisible({ timeout: 8_000 });
});

test('1.3/1.4 table-recipe: editable only in the inspector; card summary chip increments', async ({
  page,
}) => {
  await mockCommits(page);
  await settle(page);
  const card = nodeCard(page, 'apply_recipe');
  // Card shows the compact recipe summary (read-only), no grid editor.
  const summary = card.locator('[data-testid="widget-preview"][data-kind="table-recipe"]');
  await expect(summary).toContainText('recipe · 3 steps');
  await expect(card.getByTestId('table-recipe-editor')).toHaveCount(0);

  const inspector = await openInspector(page, 'apply_recipe');
  const editor = inspector.getByTestId('table-recipe-editor');
  await expect(editor).toBeVisible();
  await expect(editor.getByTestId('tr-step')).toHaveCount(3);

  // Add an op in the inspector editor → the recipe grows and commits (debounced).
  const put = waitForPut(page);
  await editor.getByTestId('tr-add-step').click();
  await editor.getByRole('menuitem', { name: /Limit/ }).click();
  await expect(editor.getByTestId('tr-step')).toHaveCount(4);
  await put;

  // The card summary follows: recipe · 4 steps.
  await expect(summary).toContainText('recipe · 4 steps');
});

test('1.4 the card shows read-only previews and wireable sockets', async ({ page }) => {
  await settle(page);
  const card = nodeCard(page, 'apply_recipe');
  // A read-only preview…
  await expect(card.locator('[data-testid="widget-preview"][data-kind="table-recipe"]')).toBeVisible();
  // …and the sockets/handles are still present (wireable).
  await expect(card.locator('.ge-socket__name', { hasText: 'recipe' })).toBeVisible();
  await expect(card.locator('.ge-handle--in').first()).toBeAttached();
  await expect(card.locator('.ge-handle--out').first()).toBeAttached();
});

test('1.8 clicking a card preview selects the node; Escape closes the inspector', async ({
  page,
}) => {
  await settle(page);
  // A click that lands directly on a preview must still select the node — no
  // dead zone left by the removed canvas-editing apparatus.
  await nodeCard(page, 'apply_recipe').getByTestId('widget-preview').first().click();
  await expect(page.getByTestId('node-inspector')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('node-inspector')).toHaveCount(0);
});
