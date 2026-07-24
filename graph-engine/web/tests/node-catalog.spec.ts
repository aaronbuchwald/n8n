import { test, expect, type Page } from '@playwright/test';

// ADR 0017 stream 17-W1 — the on-demand "Add node" catalog, against the LIVE
// demo server. W1 delivers the surface (button + anchored popover), the D2
// capability taxonomy, collapsible sections, and search; it covers D8's
// observable assertions 1 (open/close), 2 (sections + exact-id mapping), and
// 4 (search + collapse override + empty state). Click-insert, the full keyboard
// model and drag land in W2/W3 and are asserted there. This is a PURE ADDITION:
// the left Palette (palette.spec.ts) still passes alongside it.

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

  // The demo (showcase = showcase + sym + table) surfaces all five sections,
  // each with at least one entry.
  for (const category of ['input-data', 'table', 'math', 'logic', 'render-output']) {
    await expect(section(page, category)).toBeVisible();
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

  // Collapse override: fold Math shut, then a query matching only a Math entry
  // still reveals it (a search can't be swallowed by a fold).
  await search.fill('');
  const mathToggle = section(page, 'math').getByTestId('node-catalog-section-toggle');
  await mathToggle.click();
  await expect(mathToggle).toHaveAttribute('aria-expanded', 'false');
  await expect(entry(page, 'sym.evaluate_numeric')).toBeHidden();
  await search.fill('evaluate_numeric');
  await expect(entry(page, 'sym.evaluate_numeric')).toBeVisible();

  // Clearing the query restores the stored collapse state.
  await search.fill('');
  await expect(entry(page, 'sym.evaluate_numeric')).toBeHidden();

  // A garbage query dead-ends on the empty state, but the "Create new node…"
  // footer stays present as the escape hatch.
  await search.fill('zz-no-such-node');
  await expect(page.getByTestId('node-catalog-empty')).toBeVisible();
  await expect(page.getByTestId('node-catalog-new-node')).toBeVisible();

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});
