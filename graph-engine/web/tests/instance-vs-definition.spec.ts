import { test, expect, type Page } from '@playwright/test';

// ADR 0015 — instance vs definition. Clicking a node opens the INSTANCE panel
// (this node id): its inputs/outputs, plus the read-only call-site row showing
// the node's real `@main` statement as file bytes (D2). The docstring reads as
// the node TYPE's description under a "node type" caption (D4), grouped with the
// "Open node definition" drill-in (D3) — never mixed with the instance details.
// These are all read-only assertions (no save), so the test is parallel-safe.

async function gotoAndSettle(page: Page) {
  await page.goto('/');
  await expect(page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]')).toBeVisible({
    timeout: 15_000,
  });
}

/** Select a node by graph id via its header (a chip click would edit, not inspect). */
async function selectNode(page: Page, nodeId: string) {
  await page.locator(`.react-flow__node[data-id="${nodeId}"] .ge-node__header`).click();
  await expect(page.getByTestId('node-inspector')).toBeVisible();
}

test('a node click opens the instance panel, not the definition editor', async ({ page }) => {
  await gotoAndSettle(page);

  await selectNode(page, 'expr');
  const inspector = page.getByTestId('node-inspector');

  // The instance's identity — its node id, not the shared type.
  await expect(inspector.getByTestId('inspector-title')).toHaveText('expr · parse_expr');
  // Instance details are present; the definition editor (Monaco) is NOT loaded.
  await expect(inspector.getByTestId('inspector-inputs')).toBeVisible();
  await expect(inspector.getByTestId('inspector-outputs')).toBeVisible();
  await expect(inspector.getByTestId('source-editor')).toHaveCount(0);
  await expect(inspector.getByTestId('source-monaco')).toHaveCount(0);
});

test('the instance panel shows the real @main call-site statement, read-only', async ({ page }) => {
  await gotoAndSettle(page);

  await selectNode(page, 'expr');
  const inspector = page.getByTestId('node-inspector');

  // The call-site row byte-matches the node's actual @main statement.
  const source = inspector.getByTestId('callsite-source');
  await expect(source).toBeVisible();
  await expect(source).toHaveText('expr = parse_expr(text="x**2 - 5*x + 6")');

  // A `path · Lx–Ly` label points at the real file (same pattern as the editor).
  const loc = inspector.getByTestId('callsite-loc');
  await expect(loc).toContainText('showcase.py');
  await expect(loc).toContainText(/· L\d+–L\d+/);
});

test('the docstring shows as node-type metadata, beside the definition drill-in', async ({
  page,
}) => {
  await gotoAndSettle(page);

  await selectNode(page, 'expr');
  const inspector = page.getByTestId('node-inspector');
  const typeSection = inspector.getByTestId('inspector-type');

  // The doc reads as the TYPE's description under the "node type" caption.
  await expect(typeSection).toContainText('Node type');
  await expect(typeSection.getByTestId('inspector-type-name')).toHaveText('sym.parse_expr');
  await expect(typeSection.getByTestId('inspector-type-doc')).toContainText('SymPy');

  // The drill-in door sits in the same section (D3/D4 grouping).
  await expect(typeSection.getByTestId('inspector-open-definition')).toBeVisible();
});

test('open definition then "‹ back to instance" returns to the same node id', async ({ page }) => {
  await gotoAndSettle(page);

  await selectNode(page, 'expr');
  const inspector = page.getByTestId('node-inspector');

  await inspector.getByTestId('inspector-open-definition').click();
  const editor = inspector.getByTestId('source-editor');
  await expect(editor).toBeVisible();
  // The definition editor is the TYPE surface (function-scoped label).
  await expect(editor.getByTestId('source-fn-label')).toHaveText('sym.parse_expr');

  await editor.getByTestId('source-back').click();
  // Back on the SAME node's instance panel: its call-site row is showing again.
  await expect(inspector.getByTestId('inspector-title')).toHaveText('expr · parse_expr');
  await expect(inspector.getByTestId('callsite-source')).toBeVisible();
  await expect(inspector.getByTestId('source-editor')).toHaveCount(0);
});
