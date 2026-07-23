import { test, expect, type Locator, type Page } from '@playwright/test';

// ADR 0014 W1 — the workbench shell smoke suite. Proves the region model,
// sashes, collapse-to-rail, persistence, and the #5 resize-policy OVERRIDE (the
// canvas preserves its pan/zoom on a panel resize — no refit-on-resize). All
// served from localhost; the offline posture requires EXTERNAL_REQUESTS === 0.
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

test('all three sashes resize their adjacent regions', async ({ page }) => {
  const external = trackExternalRequests(page);
  await bootReady(page);

  // Left sash — widens the palette.
  const palette = page.getByTestId('palette');
  const before = await width(palette);
  await dragHandle(page, 'sash-left', 120, 0);
  expect(await width(palette)).toBeGreaterThan(before + 40);

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

  // Left.
  await page.getByTestId('collapse-left').click();
  await expect(page.getByTestId('rail-left')).toBeVisible();
  await expect(page.getByTestId('palette')).toBeHidden();
  await page.getByTestId('rail-left').click();
  await expect(page.getByTestId('rail-left')).toBeHidden();
  await expect(page.getByTestId('palette')).toBeVisible();

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

  // Widen the palette, then collapse the right dock.
  await dragHandle(page, 'sash-left', 120, 0);
  const paletteWidth = await width(page.getByTestId('palette'));
  await page.getByTestId('collapse-right').click();
  await expect(page.getByTestId('rail-right')).toBeVisible();

  // The library's autoSave is debounced (~100ms); wait until it has flushed the
  // widened palette + collapsed dock so the reload sees the persisted sizes.
  // (Collapse itself is also restored by OUR synchronous store, but the sash
  // sizes ride the library key.)
  await expect
    .poll(async () =>
      page.evaluate(() => {
        const raw = window.localStorage.getItem('react-resizable-panels:ge-workbench-main');
        if (!raw) return null;
        const groups = Object.values(JSON.parse(raw) as Record<string, { layout: number[] }>);
        return groups[0]?.layout ?? null;
      }),
    )
    .toEqual(expect.arrayContaining([0])); // right region persisted as collapsed (size 0)

  // The storage keys named in ADR 0014 D5 exist.
  const keys = await page.evaluate(() => ({
    ours: window.localStorage.getItem('ge:workbench:v1'),
    lib: window.localStorage.getItem('react-resizable-panels:ge-workbench-main'),
  }));
  expect(keys.ours, 'ge:workbench:v1 exists').not.toBeNull();
  expect(keys.lib, 'library autoSaveId key exists').not.toBeNull();

  await page.reload();
  await expect(page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]')).toBeVisible({
    timeout: 20_000,
  });

  // Collapsed state restored (rail still there), and the palette width too.
  await expect(page.getByTestId('rail-right')).toBeVisible();
  await expect(page.getByTestId('right-dock')).toBeHidden();
  expect(Math.abs((await width(page.getByTestId('palette'))) - paletteWidth)).toBeLessThan(8);

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});

test('canvas preserves its pan/zoom when a panel is resized (#5)', async ({ page }) => {
  const external = trackExternalRequests(page);
  await bootReady(page);

  // Let the initial framing settle, then snapshot the viewport transform.
  await expect.poll(async () => (await viewportTransform(page)).length).toBeGreaterThan(0);
  const before = await viewportTransform(page);

  // A sash drag changes the canvas box but must NOT re-zoom the graph.
  await dragHandle(page, 'sash-left', 140, 0);
  await dragHandle(page, 'sash-right', -140, 0);

  const after = await viewportTransform(page);
  expect(after, 'sash drag must not change the ReactFlow viewport transform').toBe(before);

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});

test('boots with every region reachable', async ({ page }) => {
  const external = trackExternalRequests(page);
  await bootReady(page);

  // Palette (left), canvas (center), and the dock placeholder (right) are all
  // present on boot with no selection.
  await expect(page.getByTestId('palette')).toBeVisible();
  await expect(page.getByTestId('flow-canvas')).toBeVisible();
  await expect(page.getByTestId('right-dock')).toBeVisible();
  await expect(page.getByTestId('dock-placeholder')).toBeVisible();

  // Selecting a node docks the Inspector as the first tab.
  await page.locator('[data-testid="spec-node"]').first().click();
  await expect(page.getByTestId('dock-tab-inspector')).toBeVisible();
  await expect(page.getByTestId('node-inspector')).toBeVisible();

  // Export and New-node stay reachable (W3 relocates them into the dock later).
  await page.getByTestId('export-button').click();
  await expect(page.getByTestId('export-panel')).toBeVisible();
  await page.getByTestId('new-node-button').click();
  await expect(page.getByTestId('new-node-panel')).toBeVisible();

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});
