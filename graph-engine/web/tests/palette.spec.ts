import { test, expect, type Page } from '@playwright/test';

// ADR 0011 stream W5 — the node palette + the `createNode` store action, against
// the LIVE demo server (no mocks on the create path). What must hold:
//  * the palette lists every registered type from GET /api/specs, grouped by
//    module (showcase / sym / table on the demo), each with a one-line doc;
//  * search filters entries by name/doc and empties groups it exhausts;
//  * clicking an entry mints a server-assisted id (POST /api/graph/mint-id),
//    adds the node, and PERSISTS it through the store's write queue
//    (PUT /api/graph) — the node survives a full reload (re-parsed from the
//    rewritten Python module);
//  * the node's unwired required inputs badge "needs wiring" (mode:"edit"
//    validation) instead of erroring;
//  * everything serves from localhost — EXTERNAL_REQUESTS must stay 0.
//
// The create test mutates the real showcase module; it restores the original
// graph (a whole-graph PUT without the node) in a finally, so the demo stays
// pristine for parallel/subsequent specs.

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

function entry(page: Page, specId: string) {
  return page.locator(`[data-testid="palette-entry"][data-spec-id="${specId}"]`);
}

test('the palette lists registered types grouped by module and search filters them', async ({
  page,
}) => {
  const external = trackExternalRequests(page);
  await openApp(page);

  const palette = page.getByTestId('palette');
  await expect(palette).toBeVisible();

  // Grouped by module: the demo registers the workspace module + both packs.
  for (const module of ['showcase', 'sym', 'table']) {
    await expect(
      palette.locator(`[data-testid="palette-group"][data-module="${module}"]`),
    ).toBeVisible();
  }

  // Entries show the type name + a one-line doc.
  const pick = entry(page, 'sym.pick');
  await expect(pick).toBeVisible();
  await expect(pick.locator('.ge-palette__entry-name')).toHaveText('pick');
  await expect(pick.locator('.ge-palette__entry-doc')).not.toBeEmpty();

  // Search filters by name; groups it exhausts disappear.
  await page.getByTestId('palette-search').fill('read_table');
  await expect(entry(page, 'table.read_table')).toBeVisible();
  await expect(pick).toBeHidden();
  await expect(
    palette.locator('[data-testid="palette-group"][data-module="sym"]'),
  ).toBeHidden();

  // No match at all → the empty state, not a blank rail.
  await page.getByTestId('palette-search').fill('zz-no-such-node');
  await expect(page.getByTestId('palette-empty')).toBeVisible();

  // Clearing restores the full palette.
  await page.getByTestId('palette-search').fill('');
  await expect(pick).toBeVisible();

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});

test('clicking an entry creates a node that persists across reload and badges needs-wiring', async ({
  page,
}) => {
  const external = trackExternalRequests(page);
  await openApp(page);

  // The pristine served graph — restored in the finally below.
  const original = await (await page.request.get('/api/graph')).json();

  let mintedId: string | null = null;
  try {
    const mint = page.waitForResponse(
      (r) => r.url().includes('/api/graph/mint-id') && r.status() === 200,
    );
    const put = page.waitForResponse(
      (r) =>
        r.url().endsWith('/api/graph') && r.request().method() === 'PUT' && r.status() === 200,
    );
    const validate = page.waitForResponse(
      (r) => r.url().includes('/api/graphs/validate') && r.status() === 200,
    );

    // sym.pick's `values` input is required and starts unwired.
    await entry(page, 'sym.pick').click();

    const minted = (await (await mint).json()) as { id: string };
    mintedId = minted.id;
    // The module already calls `pick` (the import), so the server-minted id
    // must dodge it — HD4's whole point.
    expect(mintedId).not.toBe('pick');

    // The node card is on the canvas, identified by its minted graph id.
    const card = page
      .locator('[data-testid="spec-node"]')
      .filter({ has: page.locator('[data-testid="node-id"]', { hasText: mintedId }) });
    await expect(card).toBeVisible();

    // Edit-mode validation badges the unwired required input — no error state.
    const body = (await (await validate).json()) as { ok: boolean };
    expect(body.ok).toBe(true);
    const badge = page.locator(
      `[data-testid="needs-wiring-badge"][data-node-id="${mintedId}"]`,
    );
    await expect(badge).toBeVisible();
    await expect(badge).toContainText('values');
    await expect(page.getByTestId('action-error')).toBeHidden();

    // The write queue persisted it (PUT /api/graph rewrote the real module)…
    await put;
    await page.screenshot({ path: 'tests/__screenshots__/palette.png', fullPage: false });

    // …so a full reload re-serves the graph WITH the new node (round-trip
    // through the rewritten Python, not client memory).
    await openApp(page);
    await expect(
      page
        .locator('[data-testid="spec-node"]')
        .filter({ has: page.locator('[data-testid="node-id"]', { hasText: mintedId }) }),
    ).toBeVisible();
  } finally {
    // Restore the pristine module for parallel/subsequent specs.
    const restore = await page.request.put('/api/graph', { data: { graph: original } });
    expect(restore.ok()).toBe(true);
  }

  const served = (await (await page.request.get('/api/graph')).json()) as {
    nodes: Array<{ id: string }>;
  };
  expect(served.nodes.some((n) => n.id === mintedId)).toBe(false);

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});
