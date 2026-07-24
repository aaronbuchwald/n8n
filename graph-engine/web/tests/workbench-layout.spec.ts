import { test, expect, type Locator, type Page } from '@playwright/test';

// ADR 0014 W1 — the workbench shell smoke suite (ADR 0017 W4 narrowed it to the
// `center │ right` region model — the left palette region was retired). Proves
// the region model, sashes, collapse-to-rail, persistence, and the #5
// resize-policy OVERRIDE (the canvas preserves its pan/zoom on a panel resize —
// no refit-on-resize). All served from localhost; the offline posture requires
// EXTERNAL_REQUESTS === 0.
//
// The suite is read-only against the shared demo server: it clicks Run/Export
// and opens the New-node panel (none of which mutate a module), so it stays in
// the parallel `chromium` project.

/** Collect requests leaving localhost; the offline posture requires none. */
function trackExternalRequests(page: Page): string[] {
  const external: string[] = [];
  page.on('request', (req) => {
    const { hostname } = new URL(req.url());
    if (hostname !== '127.0.0.1' && hostname !== 'localhost') external.push(req.url());
  });
  return external;
}

async function bootReady(page: Page): Promise<void> {
  await page.goto('/');
  await expect(page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]')).toBeVisible({
    timeout: 20_000,
  });
  await expect(page.getByTestId('workbench')).toBeVisible();
}

/** Drag a resize handle by `delta` px along its axis; returns nothing. */
async function dragHandle(page: Page, testid: string, dx: number, dy: number): Promise<void> {
  const handle = page.getByTestId(testid);
  const box = await handle.boundingBox();
  if (!box) throw new Error(`no bounding box for ${testid}`);
  const cx = box.x + box.width / 2;
  const cy = box.y + box.height / 2;
  await page.mouse.move(cx, cy);
  await page.mouse.down();
  await page.mouse.move(cx + dx, cy + dy, { steps: 8 });
  await page.mouse.up();
}

async function width(loc: Locator): Promise<number> {
  const box = await loc.boundingBox();
  return box?.width ?? 0;
}

async function height(loc: Locator): Promise<number> {
  const box = await loc.boundingBox();
  return box?.height ?? 0;
}

/** The ReactFlow pan/zoom transform (the viewport). Stable unless a fit runs. */
async function viewportTransform(page: Page): Promise<string> {
  return page.locator('.react-flow__viewport').first().evaluate((el) => el.style.transform);
}

/** Trigger a run so the bottom (Run results) region exists. */
async function runGraph(page: Page): Promise<void> {
  await page.getByTestId('run-button').click();
  await expect(page.getByTestId('run-results')).toBeVisible({ timeout: 20_000 });
}

/**
 * Open the New-node dock tab. ADR 0017 W4 retired the stand-in "+ New node"
 * top-bar button; the node catalog's "Create new node…" footer is the trigger.
 */
async function openNewNode(page: Page): Promise<void> {
  await page.getByTestId('add-node-button').click();
  await expect(page.getByTestId('node-catalog')).toBeVisible();
  await page.getByTestId('node-catalog-new-node').click();
}

/** Our persisted slice (`ge:workbench:v2`), or null when nothing is stored. */
async function storedLayout(
  page: Page,
): Promise<{ collapsed?: Record<string, boolean>; activeRightTab?: string | null } | null> {
  return page.evaluate(() => {
    const raw = window.localStorage.getItem('ge:workbench:v2');
    return raw ? (JSON.parse(raw) as Record<string, unknown>) : null;
  });
}

/** The persisted active right-dock tab id (the restore pointer). */
async function storedActiveTab(page: Page): Promise<string | null> {
  return (await storedLayout(page))?.activeRightTab ?? null;
}

/** Click a dock tab's tab button by tab id (the strip div wraps tab + close). */
async function activateTab(page: Page, id: string): Promise<void> {
  await page.getByTestId(`dock-tab-${id}`).getByRole('tab').click();
}

test('both sashes resize their adjacent regions', async ({ page }) => {
  const external = trackExternalRequests(page);
  await bootReady(page);

  // Right sash — widens the dock (drag left grows the right region).
  const dock = page.getByTestId('right-dock');
  const dockBefore = await width(dock);
  await dragHandle(page, 'sash-right', -120, 0);
  expect(await width(dock)).toBeGreaterThan(dockBefore + 40);

  // Bottom sash — needs a run so the bottom region exists.
  await runGraph(page);
  const results = page.getByTestId('run-results');
  const resultsBefore = await height(results);
  await dragHandle(page, 'sash-bottom', 0, -100);
  expect(await height(results)).toBeGreaterThan(resultsBefore + 30);

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});

test('each region collapses to a rail and re-expands', async ({ page }) => {
  const external = trackExternalRequests(page);
  await bootReady(page);

  // Right.
  await page.getByTestId('collapse-right').click();
  await expect(page.getByTestId('rail-right')).toBeVisible();
  await expect(page.getByTestId('right-dock')).toBeHidden();
  await page.getByTestId('rail-right').click();
  await expect(page.getByTestId('rail-right')).toBeHidden();
  await expect(page.getByTestId('right-dock')).toBeVisible();

  // Bottom (needs a run).
  await runGraph(page);
  await page.getByTestId('collapse-bottom').click();
  await expect(page.getByTestId('rail-bottom')).toBeVisible();
  await expect(page.getByTestId('run-results')).toBeHidden();
  await page.getByTestId('rail-bottom').click();
  await expect(page.getByTestId('rail-bottom')).toBeHidden();
  await expect(page.getByTestId('run-results')).toBeVisible();

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});

test('sizes and collapsed state persist across reload', async ({ page }) => {
  const external = trackExternalRequests(page);
  await bootReady(page);

  const dock = page.getByTestId('right-dock');

  // ── Size persistence: widen the dock (a sash SIZE change the library persists
  // under its autoSaveId key), reload, and confirm the width comes back. ──────
  await dragHandle(page, 'sash-right', -120, 0);

  // The library's autoSave is debounced (~100ms); wait until it has flushed the
  // widened dock so the reload sees the persisted sizes.
  await expect
    .poll(async () =>
      page.evaluate(() =>
        window.localStorage.getItem('react-resizable-panels:ge-workbench-main'),
      ),
    )
    .not.toBeNull();

  // The library's autoSaveId key named in ADR 0014 D5 exists.
  const libKey = await page.evaluate(() =>
    window.localStorage.getItem('react-resizable-panels:ge-workbench-main'),
  );
  expect(libKey, 'library autoSaveId key exists').not.toBeNull();

  const widened = await width(dock);

  await page.reload();
  await expect(page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]')).toBeVisible({
    timeout: 20_000,
  });
  expect(Math.abs((await width(dock)) - widened)).toBeLessThan(8);

  // ── Collapse persistence: collapse the dock (OUR synchronous store), reload,
  // and confirm the rail is still there. ─────────────────────────────────────
  await page.getByTestId('collapse-right').click();
  await expect(page.getByTestId('rail-right')).toBeVisible();
  await expect.poll(async () => (await storedLayout(page))?.collapsed?.right ?? null).toBe(true);

  await page.reload();
  await expect(page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]')).toBeVisible({
    timeout: 20_000,
  });
  await expect(page.getByTestId('rail-right')).toBeVisible();
  await expect(page.getByTestId('right-dock')).toBeHidden();

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});

test('canvas preserves its pan/zoom when a panel is resized (#5)', async ({ page }) => {
  const external = trackExternalRequests(page);
  await bootReady(page);

  // Let the initial framing settle, then snapshot the viewport transform.
  await expect.poll(async () => (await viewportTransform(page)).length).toBeGreaterThan(0);
  const before = await viewportTransform(page);

  // A sash drag changes the canvas box but must NOT re-zoom the graph.
  await dragHandle(page, 'sash-right', -140, 0);
  await dragHandle(page, 'sash-right', 140, 0);

  const after = await viewportTransform(page);
  expect(after, 'sash drag must not change the ReactFlow viewport transform').toBe(before);

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});

test('boots with every region reachable', async ({ page }) => {
  const external = trackExternalRequests(page);
  await bootReady(page);

  // Canvas (center) and the dock placeholder (right) are both present on boot
  // with no selection.
  await expect(page.getByTestId('flow-canvas')).toBeVisible();
  await expect(page.getByTestId('right-dock')).toBeVisible();
  await expect(page.getByTestId('dock-placeholder')).toBeVisible();

  // Selecting a node docks the Inspector as the first tab.
  await page.locator('[data-testid="spec-node"]').first().click();
  await expect(page.getByTestId('dock-tab-inspector')).toBeVisible();
  await expect(page.getByTestId('node-inspector')).toBeVisible();

  // Export and New-node live in the right dock now (W3): the toolbar / catalog
  // open them as dock tabs, and — even from a collapsed rail — the dock
  // re-expands and focuses the summoned tab so the surface never opens behind
  // the rail (D1).
  await page.getByTestId('collapse-right').click();
  await expect(page.getByTestId('rail-right')).toBeVisible();

  const dockBody = page.getByTestId('dock-body');

  await page.getByTestId('export-button').click();
  await expect(page.getByTestId('rail-right')).toBeHidden(); // dock auto-reopened
  await expect(page.getByTestId('dock-tab-export')).toBeVisible();
  await expect(dockBody.getByTestId('export-panel')).toBeVisible();

  await openNewNode(page);
  await expect(page.getByTestId('dock-tab-newnode')).toBeVisible();
  await expect(dockBody.getByTestId('new-node-panel')).toBeVisible();

  // Closing a tab via its × clears the state, so the tab and its body disappear.
  await page.getByTestId('dock-tab-close-newnode').click();
  await expect(page.getByTestId('dock-tab-newnode')).toBeHidden();
  await expect(dockBody.getByTestId('new-node-panel')).toBeHidden();

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});

// ─── W4: layout persistence + the reset / corrupt-fallback / width-memory set ──

test('reset-layout snaps every region back to defaults without a reload', async ({ page }) => {
  const external = trackExternalRequests(page);
  await bootReady(page);

  const dock = page.getByTestId('right-dock');
  const defaultDock = await width(dock);

  // Perturb: widen the dock, then collapse it to its rail.
  await dragHandle(page, 'sash-right', -140, 0);
  expect(await width(dock)).toBeGreaterThan(defaultDock + 40);
  await page.getByTestId('collapse-right').click();
  await expect(page.getByTestId('rail-right')).toBeVisible();

  // Reset — the D5 affordance restores defaults in place (no reload).
  await page.getByTestId('reset-layout').click();

  await expect(page.getByTestId('rail-right')).toBeHidden(); // dock re-expanded
  await expect(page.getByTestId('right-dock')).toBeVisible();
  await expect
    .poll(async () => Math.abs((await width(dock)) - defaultDock) < 12)
    .toBe(true);

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});

test('reset clears persisted layout so a reload boots at defaults', async ({ page }) => {
  const external = trackExternalRequests(page);
  await bootReady(page);

  const dock = page.getByTestId('right-dock');
  const defaultDock = await width(dock);

  await dragHandle(page, 'sash-right', -140, 0);
  await page.getByTestId('collapse-right').click();
  await expect(page.getByTestId('rail-right')).toBeVisible();

  // Wait until the library's debounced autoSave has flushed the modified sizes,
  // so we know the reload has real non-default state to fall back from.
  await expect
    .poll(async () =>
      page.evaluate(() =>
        window.localStorage.getItem('react-resizable-panels:ge-workbench-main'),
      ),
    )
    .not.toBeNull();

  await page.getByTestId('reset-layout').click();
  await expect(page.getByTestId('rail-right')).toBeHidden();

  // Our slice is back to the default (no region collapsed). Reset removes both
  // key families and re-commits DEFAULTS, so the persisted collapse map is clean.
  await expect
    .poll(async () => (await storedLayout(page))?.collapsed ?? null)
    .toEqual({ right: false, bottom: false });

  await page.reload();
  await expect(page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]')).toBeVisible({
    timeout: 20_000,
  });

  // Defaults survived the reload: dock expanded, back at its default width.
  await expect(page.getByTestId('rail-right')).toBeHidden();
  await expect(page.getByTestId('right-dock')).toBeVisible();
  expect(Math.abs((await width(dock)) - defaultDock)).toBeLessThan(12);

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});

test('the active dock tab is persisted and drives which tab is shown', async ({ page }) => {
  const external = trackExternalRequests(page);
  await bootReady(page);

  // Inspector (inspector-kind) then Export (code-kind); the summoned Export tab
  // auto-focuses (appear-detection) and its id is written to our slice.
  await page.locator('[data-testid="spec-node"]').first().click();
  await expect(page.getByTestId('dock-tab-inspector')).toBeVisible();
  await page.getByTestId('export-button').click();
  await expect(page.getByTestId('dock-tab-export')).toBeVisible();
  const dockBody = page.getByTestId('dock-body');
  await expect(dockBody.getByTestId('export-panel')).toBeVisible();
  await expect.poll(() => storedActiveTab(page)).toBe('export');

  // Switch to the inspector tab: persisted, and it is the rendered body.
  await activateTab(page, 'inspector');
  await expect(dockBody.getByTestId('node-inspector')).toBeVisible();
  await expect(dockBody.getByTestId('export-panel')).toBeHidden();
  await expect.poll(() => storedActiveTab(page)).toBe('inspector');

  // The pointer survives a reload. The tab-owning app state (selected node,
  // export buffer) is transient and NOT persisted, so no tab renders on boot —
  // the dock shows its placeholder — but the restore pointer is intact for the
  // next time that tab is present.
  await page.reload();
  await expect(page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]')).toBeVisible({
    timeout: 20_000,
  });
  await expect(page.getByTestId('dock-placeholder')).toBeVisible();
  expect(await storedActiveTab(page)).toBe('inspector');

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});

test('the dock remembers a separate width for inspector and code tab kinds', async ({ page }) => {
  const external = trackExternalRequests(page);
  await bootReady(page);
  const dock = page.getByTestId('right-dock');

  // One inspector-kind tab and one code-kind tab (Export).
  await page.locator('[data-testid="spec-node"]').first().click();
  await expect(page.getByTestId('dock-tab-inspector')).toBeVisible();
  await page.getByTestId('export-button').click();
  await expect(page.getByTestId('dock-tab-export')).toBeVisible();

  // On the code tab, widen the dock; that width is remembered for `code`.
  await dragHandle(page, 'sash-right', -140, 0);
  const codeWidth = await width(dock);

  // Switch to the inspector tab — the dock snaps to the narrower inspector width.
  await activateTab(page, 'inspector');
  await expect.poll(async () => await width(dock)).toBeLessThan(codeWidth - 40);
  const inspectorWidth = await width(dock);

  // Back to the code tab — the widened code width returns (within tolerance).
  await activateTab(page, 'export');
  await expect.poll(async () => Math.abs((await width(dock)) - codeWidth)).toBeLessThan(16);

  // And the inspector width is stable when we return to it.
  await activateTab(page, 'inspector');
  await expect.poll(async () => Math.abs((await width(dock)) - inspectorWidth)).toBeLessThan(16);

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});

test('a corrupt saved layout falls back to defaults instead of wedging the shell', async ({
  page,
}) => {
  const external = trackExternalRequests(page);
  // Seed junk under our versioned key BEFORE any app script runs.
  await page.addInitScript(() => {
    window.localStorage.setItem('ge:workbench:v2', '{not json');
  });
  await bootReady(page);

  // Boots at defaults: every region reachable, none collapsed, dock placeholder up.
  await expect(page.getByTestId('flow-canvas')).toBeVisible();
  await expect(page.getByTestId('right-dock')).toBeVisible();
  await expect(page.getByTestId('dock-placeholder')).toBeVisible();
  await expect(page.getByTestId('rail-right')).toBeHidden();

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});

test('summoning New node behind a collapsed dock auto-reveals it', async ({ page }) => {
  const external = trackExternalRequests(page);
  await bootReady(page);

  // Collapse the dock to its rail, then summon the New-node surface.
  await page.getByTestId('collapse-right').click();
  await expect(page.getByTestId('rail-right')).toBeVisible();

  await openNewNode(page);

  // The dock re-expands onto the summoned surface, which is the active tab.
  await expect(page.getByTestId('rail-right')).toBeHidden();
  await expect(page.getByTestId('right-dock')).toBeVisible();
  const dockBody = page.getByTestId('dock-body');
  await expect(page.getByTestId('dock-tab-newnode')).toBeVisible();
  await expect(dockBody.getByTestId('new-node-panel')).toBeVisible();
  await expect(page.getByTestId('dock-tab-newnode').getByRole('tab')).toHaveAttribute(
    'aria-selected',
    'true',
  );

  // Closing it via its × clears the tab and its body.
  await page.getByTestId('dock-tab-close-newnode').click();
  await expect(page.getByTestId('dock-tab-newnode')).toBeHidden();
  await expect(dockBody.getByTestId('new-node-panel')).toBeHidden();

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});

test('the collapsed bottom rail shows the executed-node count badge', async ({ page }) => {
  const external = trackExternalRequests(page);
  await bootReady(page);
  await runGraph(page);

  // Read the executed-node count from the run-results summary ("N nodes executed").
  const summary = (await page.locator('.ge-results__sub').first().textContent()) ?? '';
  const expected = Number(/(\d+)\s+nodes executed/.exec(summary)?.[1]);
  expect(expected, 'run summary reports an executed-node count').toBeGreaterThan(0);

  // Collapse the bottom region; its rail carries that same count as a badge.
  await page.getByTestId('collapse-bottom').click();
  const rail = page.getByTestId('rail-bottom');
  await expect(rail).toBeVisible();
  const badge = rail.locator('.ge-rail__badge');
  await expect(badge).toBeVisible();
  expect(Number((await badge.textContent())?.trim())).toBe(expected);

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});
