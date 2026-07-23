import { test, expect, type Page } from '@playwright/test';
import { readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// ADR 0007 stream W, reconciled onto the 8-S1 store — the calc widget against
// the LIVE demo server (no mocks), on capacity_check's `handcalc` node
// (graph id `steps`). What must hold end-to-end:
//  * the node's derived sockets (C_min, F_max) render on the canvas, resolved
//    from the STORE's derivedByNode view over the committed literal;
//  * editing the equation shows live (debounced) symbol chips: an added symbol
//    is highlighted before any commit, and NOTHING is saved per keystroke;
//  * an invalid equation shows the server's error inline and does not commit;
//  * committing updates the node's sockets on the canvas AND persists through
//    the store's single-flight queue (one PUT of the scoped graph route);
//  * removing a wired symbol prunes its edge in the SAME save and toasts what
//    was unwired (D8 prune-with-toast);
//  * the canvas never fetches a committed derivation the store already has —
//    the commit ingests the editor's own derive outcome (no parallel path);
//  * everything serves from localhost — EXTERNAL_REQUESTS must stay 0.
//
// The test REALLY rewrites examples/capacity_check/capacity_check.py through
// the server and restores the pristine graph in a finally; it runs in its own
// sequenced project (see playwright.config.ts) because it mutates the shared
// demo workspace.

const HERE = path.dirname(fileURLToPath(import.meta.url));
const MODULE_PY = path.resolve(HERE, '..', '..', 'examples', 'capacity_check', 'capacity_check.py');

const GRAPH_ROUTE = '/api/graphs/capacity_check/graph';
// capacity_check's handcalc is a two-line calc since ADR 0016: the equation
// plus the assertion that judges it (`check = margin > 0`), single-sourced.
// The edits below append to / replace this whole value.
const ORIGINAL_EQ = 'margin = C_min - F_max\ncheck = margin > 0';

test.describe.configure({ mode: 'serial' });

/** Collect requests leaving localhost; the offline posture requires none. */
function trackExternalRequests(page: Page): string[] {
  const external: string[] = [];
  page.on('request', (req) => {
    const { hostname } = new URL(req.url());
    if (hostname !== '127.0.0.1' && hostname !== 'localhost') external.push(req.url());
  });
  return external;
}

/** Every POST body sent to the handcalc derive endpoint, in order. */
function trackDeriveCalls(page: Page): string[] {
  const bodies: string[] = [];
  page.on('request', (req) => {
    if (req.method() === 'POST' && req.url().includes('/api/specs/sym.handcalc/derive')) {
      const data: unknown = req.postDataJSON();
      if (data && typeof data === 'object' && 'value' in data) {
        bodies.push(String((data as { value: unknown }).value));
      }
    }
  });
  return bodies;
}

function trackGraphPuts(page: Page): { count: () => number } {
  let n = 0;
  page.on('request', (req) => {
    if (req.method() === 'PUT' && req.url().includes(GRAPH_ROUTE)) n += 1;
  });
  return { count: () => n };
}

const waitForGraphPut = (page: Page) =>
  page.waitForResponse(
    (r) => r.url().includes(GRAPH_ROUTE) && r.request().method() === 'PUT' && r.status() === 200,
  );

function stepsNode(page: Page) {
  return page.locator('.react-flow__node[data-id="steps"]');
}

function socketName(page: Page, name: string) {
  return stepsNode(page).locator(`.ge-socket__name[title="${name}"]`);
}

function chip(page: Page, symbol: string) {
  return page.locator(`[data-testid="calc-symbol-chip"][data-symbol="${symbol}"]`);
}

test('calc widget: live derived chips, invalid-equation refusal, commit reshapes sockets, symbol removal prunes its edge with a toast — all through the store', async ({
  page,
}) => {
  test.setTimeout(120_000);
  const external = trackExternalRequests(page);
  const deriveCalls = trackDeriveCalls(page);
  const puts = trackGraphPuts(page);

  await page.goto('/?graph=capacity_check');
  await expect(page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]')).toBeVisible({
    timeout: 15_000,
  });
  const original: unknown = await (await page.request.get(GRAPH_ROUTE)).json();
  const moduleBefore = readFileSync(MODULE_PY, 'utf8');

  try {
    // --- derived sockets render from the store on plain load ----------------
    // C_min / F_max are not in the static spec; they exist only because the
    // store resolved the committed literal through /derive and the canvas
    // folded state.derivedByNode into the node's inputs.
    await expect(socketName(page, 'C_min')).toBeVisible({ timeout: 15_000 });
    await expect(socketName(page, 'F_max')).toBeVisible();
    await expect(socketName(page, 'lines')).toBeVisible();

    // --- open the calc editor (ADR 0013: in the inspector, not on the card) -
    await stepsNode(page).locator('[data-testid="node-title"]').click();
    const inspector = page.getByTestId('node-inspector');
    await expect(inspector).toBeVisible();
    const editor = inspector.getByTestId('widget-editor-calc-input');
    await expect(editor).toBeVisible();
    await expect(editor).toHaveValue(ORIGINAL_EQ);

    // --- 1.6 derived sockets are inspectable ---------------------------------
    // C_min / F_max are derived from the equation and WIRED (from select_extreme):
    // the inspector lists them read-only, with their wired source tag, no editor.
    const cMinRow = inspector
      .locator('[data-testid="inspector-input"]')
      .filter({ has: page.locator('.ge-inspector__socket', { hasText: /^C_min$/ }) });
    await expect(cMinRow).toBeVisible();
    await expect(cMinRow.locator('.ge-inspector__tag--wired')).toBeVisible();
    await expect(cMinRow.getByTestId('inspector-widget-slot')).toHaveCount(0);

    // --- live (debounced) derive: an added symbol chips up, uncommitted -----
    const putsBeforeTyping = puts.count();
    await editor.fill(`${ORIGINAL_EQ} + extra`);
    await expect(chip(page, 'extra')).toHaveAttribute('data-state', 'added', { timeout: 10_000 });
    await expect(chip(page, 'C_min')).toHaveAttribute('data-state', 'kept');
    // Typing alone committed nothing: no save left, no socket appeared.
    expect(puts.count()).toBe(putsBeforeTyping);
    await expect(socketName(page, 'extra')).toHaveCount(0);

    // --- an invalid equation shows the inline error and refuses to commit ---
    await editor.fill('margin = = C_min');
    await expect(page.getByTestId('calc-derive-error')).toBeVisible({ timeout: 10_000 });
    const putsBeforeInvalid = puts.count();
    await editor.press('Control+Enter'); // try to apply anyway
    await expect(page.getByTestId('calc-derive-error')).toBeVisible();
    await page.waitForTimeout(700); // a commit would have PUT by now
    expect(puts.count()).toBe(putsBeforeInvalid);
    const served: { nodes: Array<{ id: string; inputs: Record<string, unknown> }> } = await (
      await page.request.get(GRAPH_ROUTE)
    ).json();
    expect(served.nodes.find((n) => n.id === 'steps')?.inputs.lines).toBe(ORIGINAL_EQ);

    // --- a valid commit reshapes the node's sockets -------------------------
    const withSafety = `${ORIGINAL_EQ} - safety`;
    await editor.fill(withSafety);
    await expect(chip(page, 'safety')).toHaveAttribute('data-state', 'added', { timeout: 10_000 });
    // The freshly-added symbol is required by default; give it an inline value.
    await page.locator('[data-testid="calc-symbol-value"][data-symbol="safety"]').fill('2');
    const commit1 = waitForGraphPut(page);
    await editor.press('Control+Enter');
    await commit1;
    // The new socket is on the canvas — folded from the store's derivedByNode.
    await expect(socketName(page, 'safety')).toBeVisible({ timeout: 10_000 });
    await expect(socketName(page, 'C_min')).toBeVisible();

    // --- 1.6 an unwired derived symbol is editable in the inspector ----------
    // `safety` is derived + unwired (given an inline literal): the inspector
    // renders a number editor for it, so derived sockets can be given values.
    const safetyRow = inspector
      .locator('[data-testid="inspector-input"]')
      .filter({ has: page.locator('.ge-inspector__socket', { hasText: /^safety$/ }) });
    await expect(safetyRow.getByTestId('inspector-widget-slot')).toBeVisible({ timeout: 10_000 });
    await expect(safetyRow.getByTestId('widget-editor-number')).toBeVisible();
    // No parallel derive path: the commit INGESTED the editor's own verdict, so
    // the canvas needed no second derive POST for the committed literal.
    expect(deriveCalls.filter((v) => v === withSafety).length).toBe(1);

    await page.screenshot({
      path: path.join(HERE, '__screenshots__', 'calc-widget.png'),
      fullPage: true,
    });

    // --- removing a wired symbol prunes its edge, same save, with a toast ---
    await expect(editor).toHaveValue(withSafety); // draft reset to the committed text
    await editor.fill('margin = C_min - safety');
    // The wired F_max chips as removed + "will unwire" BEFORE the commit.
    await expect(chip(page, 'F_max')).toHaveAttribute('data-state', 'removed', { timeout: 10_000 });
    await expect(chip(page, 'F_max')).toContainText('will unwire');
    const commit2 = waitForGraphPut(page);
    await editor.press('Control+Enter');
    await commit2;
    const toast = page.getByTestId('calc-toast');
    await expect(toast).toBeVisible({ timeout: 10_000 });
    await expect(toast).toHaveText('F_max removed from equation — unwired from max_force');
    await expect(socketName(page, 'F_max')).toHaveCount(0);
    // The edge is gone server-side too — pruned in the SAME save.
    const afterPrune: { edges: Array<{ target: string; targetInput: string }> } = await (
      await page.request.get(GRAPH_ROUTE)
    ).json();
    expect(
      afterPrune.edges.some((e) => e.target === 'steps' && e.targetInput === 'F_max'),
    ).toBe(false);
    expect(
      afterPrune.edges.some((e) => e.target === 'steps' && e.targetInput === 'C_min'),
    ).toBe(true);
  } finally {
    // Restore the pristine wiring (rewrites the real module back)…
    const res = await page.request.put(GRAPH_ROUTE, { data: { graph: original } });
    expect(res.ok()).toBe(true);
    // …then the pristine BYTES: the write-back canonicalizes the rewritten
    // statement (quote/subscript style), and the server re-reads the module
    // from disk per request, so restoring the authored text is safe and keeps
    // the repo clean across runs.
    writeFileSync(MODULE_PY, moduleBefore);
  }

  // Restored: the served graph carries the original equation and both wires.
  const restored: {
    nodes: Array<{ id: string; inputs: Record<string, unknown> }>;
    edges: Array<{ target: string; targetInput: string }>;
  } = await (await page.request.get(GRAPH_ROUTE)).json();
  expect(restored.nodes.find((n) => n.id === 'steps')?.inputs.lines).toBe(ORIGINAL_EQ);
  expect(
    restored.edges.some((e) => e.target === 'steps' && e.targetInput === 'F_max'),
  ).toBe(true);

  expect(external).toEqual([]);
});
