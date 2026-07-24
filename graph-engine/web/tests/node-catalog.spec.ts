import { test, expect, type Page } from '@playwright/test';

// The destructive tests (insert/multi-add/drag) really mutate the showcase
// graph and restore it in a finally — run them serially so a restore never
// races the next test's mutation (they own the workspace via the `catalog`
// project; see playwright.config.ts).
test.describe.configure({ mode: 'serial' });

// ADR 0017 — the on-demand "Add node" catalog, against the LIVE demo server.
//
// Stream 17-W1 delivered the surface (button + anchored popover), the D2
// capability taxonomy, collapsible sections, and search — D8's observable
// assertions 1 (open/close), 2 (sections + exact-id mapping), and 4 (search +
// collapse override + empty state).
//
// Stream 17-W2 adds the D5 keyboard model + collapsed-by-default sections —
// D8's assertions 3 (every open starts collapsed; a header click expands, a
// reopen re-collapses; search still reveals matches), 5 (keyboard insert:
// Ctrl+K / arrows / Enter → a node exists + inspector opens), and 6 (Alt+Enter
// multi-add keeps the catalog open). Section collapse is now EPHEMERAL — reset
// each open — so nothing persists across reload and Reset layout has no catalog
// slice to clear. The insert tests mutate the real demo module and restore the
// pristine graph in a `finally`, exactly like palette.spec.ts.
//
// Stream 17-W3 adds the D6 drag-out-of-catalog assertion 7 (the ghost state on
// dragstart, cancel-restores vs drop-closes, and a canvas node minted at the
// drop point through the reused PALETTE_SPEC_MIME contract). This is a PURE
// ADDITION: the left Palette (palette.spec.ts) still passes alongside it.

/** Collect requests leaving localhost; the offline posture requires none. */
function trackExternalRequests(page: Page): string[] {
  const external: string[] = [];
  page.on('request', (req) => {
    const { hostname } = new URL(req.url());
    if (hostname !== '127.0.0.1' && hostname !== 'localhost') external.push(req.url());
  });
  return external;
}

async function openApp(page: Page): Promise<void> {
  await page.goto('/');
  await expect(page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]')).toBeVisible({
    timeout: 15_000,
  });
}

function section(page: Page, category: string) {
  return page.locator(`[data-testid="node-catalog-section"][data-category="${category}"]`);
}

function entry(page: Page, specId: string) {
  return page.locator(`[data-testid="node-catalog-entry"][data-spec-id="${specId}"]`);
}

/** Expand a collapsed-by-default section by clicking its header toggle. */
async function expandSection(page: Page, category: string) {
  const toggle = section(page, category).getByTestId('node-catalog-section-toggle');
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
}

test('opens from the top bar with the search focused and closes on Escape / outside click', async ({
  page,
}) => {
  const external = trackExternalRequests(page);
  await openApp(page);

  const catalog = page.getByTestId('node-catalog');
  await expect(catalog).toBeHidden();

  // Click the trigger → the popover opens with its search autofocused.
  await page.getByTestId('add-node-button').click();
  await expect(catalog).toBeVisible();
  await expect(page.getByTestId('node-catalog-search')).toBeFocused();

  // Escape with an empty query closes it.
  await page.keyboard.press('Escape');
  await expect(catalog).toBeHidden();

  // Reopen and dismiss by clicking outside the popover.
  await page.getByTestId('add-node-button').click();
  await expect(catalog).toBeVisible();
  await page.locator('.ge-topbar__title').click();
  await expect(catalog).toBeHidden();

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});

test('groups nodes into the capability sections, with the exact-id map beating the module default', async ({
  page,
}) => {
  const external = trackExternalRequests(page);
  await openApp(page);

  await page.getByTestId('add-node-button').click();
  await expect(page.getByTestId('node-catalog')).toBeVisible();

  // The demo (showcase = showcase + sym + table) surfaces all five sections.
  // Sections open collapsed (headers + counts only), so their entries appear
  // only once the header is clicked to expand.
  for (const category of ['input-data', 'table', 'math', 'logic', 'render-output']) {
    await expect(section(page, category)).toBeVisible();
    await expect(
      section(page, category).locator('[data-testid="node-catalog-entry"]').first(),
    ).toBeHidden();
    await expandSection(page, category);
    await expect(
      section(page, category).locator('[data-testid="node-catalog-entry"]').first(),
    ).toBeVisible();
  }

  // The exact-id map wins over the module default: table.read_table is
  // Input/Data (capability = bringing data in), not Table.
  await expect(section(page, 'input-data').locator('[data-spec-id="table.read_table"]')).toBeVisible();
  await expect(entry(page, 'table.read_table')).toHaveAttribute('data-category', 'input-data');

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});

test('search filters across sections, overrides collapse, and shows an empty state with the new-node escape hatch', async ({
  page,
}) => {
  const external = trackExternalRequests(page);
  await openApp(page);

  await page.getByTestId('add-node-button').click();
  const search = page.getByTestId('node-catalog-search');

  // A query narrows to matching entries; sections it exhausts disappear.
  await search.fill('read_table');
  await expect(entry(page, 'table.read_table')).toBeVisible();
  await expect(section(page, 'math')).toBeHidden();

  // Collapse override: Math opens collapsed (every open does), yet a query
  // matching only a Math entry still reveals it — a search can't be swallowed
  // by a fold.
  await search.fill('');
  const mathToggle = section(page, 'math').getByTestId('node-catalog-section-toggle');
  await expect(mathToggle).toHaveAttribute('aria-expanded', 'false');
  await expect(entry(page, 'sym.evaluate_numeric')).toBeHidden();
  await search.fill('evaluate_numeric');
  await expect(entry(page, 'sym.evaluate_numeric')).toBeVisible();

  // Clearing the query returns to the collapsed-by-default view.
  await search.fill('');
  await expect(entry(page, 'sym.evaluate_numeric')).toBeHidden();

  // A garbage query dead-ends on the empty state, but the "Create new node…"
  // footer stays present as the escape hatch.
  await search.fill('zz-no-such-node');
  await expect(page.getByTestId('node-catalog-empty')).toBeVisible();
  await expect(page.getByTestId('node-catalog-new-node')).toBeVisible();

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});

async function openCatalog(page: Page): Promise<void> {
  await page.getByTestId('add-node-button').click();
  await expect(page.getByTestId('node-catalog')).toBeVisible();
}

/** The single row carrying the virtual highlight (aria-activedescendant). */
function activeEntry(page: Page) {
  return page.locator('[data-testid="node-catalog-entry"][aria-selected="true"]');
}

/** Await the next successful id mint (each insert funnels through it). */
function nextMint(page: Page) {
  return page.waitForResponse(
    (r) => r.url().includes('/api/graph/mint-id') && r.status() === 200,
  );
}

// ── D8 assertion 5 (keyboard open) — Ctrl/Cmd+K ──────────────────────────────
test('Ctrl/Cmd+K opens the catalog with the search focused, and again closes it', async ({
  page,
}) => {
  const external = trackExternalRequests(page);
  await openApp(page);

  const catalog = page.getByTestId('node-catalog');
  await expect(catalog).toBeHidden();

  // The quick-switcher shortcut opens it (guarded away from editable targets),
  // search autofocused.
  await page.keyboard.press('Control+k');
  await expect(catalog).toBeVisible();
  await expect(page.getByTestId('node-catalog-search')).toBeFocused();

  // Pressing it again closes.
  await page.keyboard.press('Control+k');
  await expect(catalog).toBeHidden();

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});

// ── D5 virtual highlight — roving aria-activedescendant across sections ───────
test('arrow keys rove a single virtual highlight across section boundaries and wrap', async ({
  page,
}) => {
  const external = trackExternalRequests(page);
  await openApp(page);
  await openCatalog(page);

  // Sections open collapsed, so there are no navigable rows until we expand
  // them; expand all five so the highlight has a list to rove across sections.
  for (const category of ['input-data', 'table', 'math', 'logic', 'render-output']) {
    await expandSection(page, category);
  }

  // Exactly one row is highlighted — the first visible entry.
  await expect(activeEntry(page)).toHaveCount(1);
  const first = await activeEntry(page).getAttribute('data-spec-id');
  const search = page.getByTestId('node-catalog-search');
  // The highlight is virtual (aria-activedescendant on the search, not DOM focus).
  await expect(search).toHaveAttribute('aria-activedescendant', `ge-catalog-opt-${first}`);

  // ↓ advances the highlight to a different row (still exactly one).
  await search.press('ArrowDown');
  await expect(activeEntry(page)).toHaveCount(1);
  const second = await activeEntry(page).getAttribute('data-spec-id');
  expect(second).not.toBe(first);

  // From the first row, ↑ wraps to the LAST visible row — which lives in the
  // last non-empty section (render-output), proving the highlight flows across
  // section boundaries rather than clamping within one.
  await search.press('Home');
  await search.press('ArrowUp');
  await expect(activeEntry(page)).toHaveCount(1);
  await expect(activeEntry(page)).toHaveAttribute('data-category', 'render-output');

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});

// ── D8 assertion 3 — sections start collapsed on every open; search still reveals ─
test('sections open collapsed, a header click expands, a reopen re-collapses, and search still reveals matches', async ({
  page,
}) => {
  const external = trackExternalRequests(page);
  await openApp(page);
  await openCatalog(page);

  // On open every section is collapsed: the Math header is present and reads
  // collapsed, but its entries are not rendered until it is expanded.
  const mathToggle = section(page, 'math').getByTestId('node-catalog-section-toggle');
  await expect(mathToggle).toHaveAttribute('aria-expanded', 'false');
  await expect(entry(page, 'sym.evaluate_numeric')).toBeHidden();

  // Clicking the header expands the section; clicking again re-collapses it.
  await mathToggle.click();
  await expect(mathToggle).toHaveAttribute('aria-expanded', 'true');
  await expect(entry(page, 'sym.evaluate_numeric')).toBeVisible();
  await mathToggle.click();
  await expect(mathToggle).toHaveAttribute('aria-expanded', 'false');
  await expect(entry(page, 'sym.evaluate_numeric')).toBeHidden();

  // Expand it, then close and reopen — the catalog is collapsed again (the
  // expand state is ephemeral, reset on every open, never persisted).
  await mathToggle.click();
  await expect(mathToggle).toHaveAttribute('aria-expanded', 'true');
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('node-catalog')).toBeHidden();
  await openCatalog(page);
  await expect(section(page, 'math').getByTestId('node-catalog-section-toggle')).toHaveAttribute(
    'aria-expanded',
    'false',
  );
  await expect(entry(page, 'sym.evaluate_numeric')).toBeHidden();

  // Nothing persisted the collapse: the retired `ge:catalog:v1` key is absent.
  const stored = await page.evaluate(() => window.localStorage.getItem('ge:catalog:v1'));
  expect(stored).toBeNull();

  // Search still auto-reveals matches even though sections are collapsed by
  // default — a Math match surfaces without expanding anything.
  const search = page.getByTestId('node-catalog-search');
  await search.fill('evaluate_numeric');
  await expect(entry(page, 'sym.evaluate_numeric')).toBeVisible();
  // Clearing the query returns to the collapsed-by-default view.
  await search.fill('');
  await expect(entry(page, 'sym.evaluate_numeric')).toBeHidden();

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});

// ── D8 assertion 5 — keyboard insert (type → Enter) creates + selects a node ──
test('typing then Enter inserts the highlighted node, closes the catalog and opens the inspector', async ({
  page,
}) => {
  const external = trackExternalRequests(page);
  await openApp(page);

  const original = await (await page.request.get('/api/graph')).json();
  let mintedId: string | null = null;
  try {
    await openCatalog(page);
    const search = page.getByTestId('node-catalog-search');

    // Narrow to a single demo spec so the highlighted (first visible) row is
    // deterministic, then insert it with Enter.
    await search.fill('latex_to_mathml');
    await expect(entry(page, 'sym.latex_to_mathml')).toBeVisible();
    await expect(activeEntry(page)).toHaveAttribute('data-spec-id', 'sym.latex_to_mathml');

    const mint = nextMint(page);
    const put = page.waitForResponse(
      (r) => r.url().endsWith('/api/graph') && r.request().method() === 'PUT' && r.status() === 200,
    );
    await search.press('Enter');

    mintedId = ((await (await mint).json()) as { id: string }).id;
    await put;

    // The catalog closed on insert (D4).
    await expect(page.getByTestId('node-catalog')).toBeHidden();

    // A canvas node of the inserted type exists, identified by its minted id…
    const card = page
      .locator('[data-testid="spec-node"]')
      .filter({ has: page.locator('[data-testid="node-id"]', { hasText: mintedId }) });
    await expect(card).toBeVisible();

    // …and it is selected, so the Inspector docked (the natural next step, D4).
    await expect(page.getByTestId('node-inspector')).toBeVisible();
    await expect(page.getByTestId('dock-tab-inspector')).toBeVisible();
  } finally {
    const restore = await page.request.put('/api/graph', { data: { graph: original } });
    expect(restore.ok()).toBe(true);
  }

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});

// ── D8 assertion 6 — Alt+Enter multi-add keeps the catalog open ──────────────
test('Alt+Enter inserts without closing so several nodes can be added in one visit', async ({
  page,
}) => {
  const external = trackExternalRequests(page);
  await openApp(page);

  const original = await (await page.request.get('/api/graph')).json();
  const minted: string[] = [];
  try {
    await openCatalog(page);
    const search = page.getByTestId('node-catalog-search');
    await search.fill('latex_to_mathml');
    await expect(activeEntry(page)).toHaveAttribute('data-spec-id', 'sym.latex_to_mathml');

    // First Alt+Enter: a node is minted and the catalog STAYS open.
    let mint = nextMint(page);
    await search.press('Alt+Enter');
    minted.push(((await (await mint).json()) as { id: string }).id);
    await expect(page.getByTestId('node-catalog')).toBeVisible();

    // Second Alt+Enter: a second, distinct node — still open.
    mint = nextMint(page);
    await search.press('Alt+Enter');
    minted.push(((await (await mint).json()) as { id: string }).id);
    await expect(page.getByTestId('node-catalog')).toBeVisible();

    expect(minted[0]).not.toBe(minted[1]);
    for (const id of minted) {
      await expect(
        page
          .locator('[data-testid="spec-node"]')
          .filter({ has: page.locator('[data-testid="node-id"]', { hasText: id }) }),
      ).toBeVisible();
    }
  } finally {
    const restore = await page.request.put('/api/graph', { data: { graph: original } });
    expect(restore.ok()).toBe(true);
  }

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});

// ── D8 assertion 7 — drag out of the catalog: ghost state + drop-to-create ────
// The entry's own dragstart writes the drag payload (via the component, not the
// test), so the drop reading it back proves the payload matches GraphView's
// existing PALETTE_SPEC_MIME contract byte-for-byte. A cancelled drag restores
// the catalog; a real drop closes it and mints a node at the drop point.
test('dragging an entry ghosts the popover, and a canvas drop creates a node at the drop point and closes it', async ({
  page,
}) => {
  const external = trackExternalRequests(page);
  await openApp(page);

  const original = await (await page.request.get('/api/graph')).json();
  let mintedId: string | null = null;
  try {
    await openCatalog(page);
    const search = page.getByTestId('node-catalog-search');
    await search.fill('latex_to_mathml');
    const row = entry(page, 'sym.latex_to_mathml');
    await expect(row).toBeVisible();

    const catalog = page.getByTestId('node-catalog');
    const canvas = page.getByTestId('flow-canvas');
    const canvasBox = await canvas.boundingBox();
    expect(canvasBox).not.toBeNull();
    if (!canvasBox) return;
    const dropX = Math.round(canvasBox.x + canvasBox.width * 0.44);
    const dropY = Math.round(canvasBox.y + canvasBox.height * 0.82);

    // A fresh DataTransfer flows through the real dragstart handler (which sets
    // the MIME payload) into the canvas drop — the same object the browser
    // would carry across a genuine drag.
    const dataTransfer = await page.evaluateHandle(() => new DataTransfer());

    // ── cancel branch: dragstart ghosts the popover; a dragend with no drop
    //    (dropEffect "none") restores it, still open, still on the same query.
    await row.dispatchEvent('dragstart', { dataTransfer });
    await expect(catalog).toHaveAttribute('data-dragging', 'true');
    await row.dispatchEvent('dragend', { dataTransfer });
    await expect(catalog).not.toHaveAttribute('data-dragging', 'true');
    await expect(catalog).toBeVisible();

    // ── drop branch: dragstart ghosts again, the canvas drop mints the node at
    //    the drop point, and the dragend (a real drop ⇒ dropEffect "copy")
    //    closes the catalog.
    await row.dispatchEvent('dragstart', { dataTransfer });
    await expect(catalog).toHaveAttribute('data-dragging', 'true');

    const mint = nextMint(page);
    const put = page.waitForResponse(
      (r) => r.url().endsWith('/api/graph') && r.request().method() === 'PUT' && r.status() === 200,
    );
    await canvas.dispatchEvent('drop', { dataTransfer, clientX: dropX, clientY: dropY });
    mintedId = ((await (await mint).json()) as { id: string }).id;
    await put;

    await page.evaluate((dt) => ((dt as DataTransfer).dropEffect = 'copy'), dataTransfer);
    await row.dispatchEvent('dragend', { dataTransfer });

    // The drop closed the catalog (D6).
    await expect(catalog).toBeHidden();

    // A canvas node of the dropped type exists, born at the drop point.
    const card = page
      .locator('[data-testid="spec-node"]')
      .filter({ has: page.locator('[data-testid="node-id"]', { hasText: mintedId }) });
    await expect(card).toBeVisible();
    const cardBox = await card.boundingBox();
    expect(cardBox).not.toBeNull();
    if (!cardBox) return;
    expect(Math.abs(cardBox.x - dropX)).toBeLessThanOrEqual(2);
    expect(Math.abs(cardBox.y - dropY)).toBeLessThanOrEqual(2);
  } finally {
    const restore = await page.request.put('/api/graph', { data: { graph: original } });
    expect(restore.ok()).toBe(true);
  }

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});
