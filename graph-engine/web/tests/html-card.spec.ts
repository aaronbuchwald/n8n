import { test, expect, type Page } from '@playwright/test';

// ADR 0010 stream 10-K: the `html-card` kind end-to-end against the LIVE demo
// (no spec rewriting — the packs really declare it since 10-E/10-K). What must
// hold (D5/D6/D7):
//  * `sym.render_math_card`'s node shows its MathML card INSIDE a sandboxed
//    iframe in the result strip — sandbox="" exactly (no allow-scripts), the
//    declared height, srcDoc (never dangerouslySetInnerHTML);
//  * before a run the surface shows a text placeholder, no iframe (canvas-cost
//    rule: the iframe exists only once a value does);
//  * shell chrome (title, sockets, handles, widget chips) stays shell-owned;
//  * the results panel resolves the same kind for the output node (dashboard)
//    with the same sandbox posture, replacing the old string-iframe special
//    case;
//  * a node that publishes its own card height (`sheet.calc_card` on
//    capacity_check) sizes the frame from that per-instance value instead of
//    the statically declared config height — a scriptless iframe cannot
//    measure itself, so the height comes from the run, from OUTSIDE the frame,
//    with the sandbox untouched;
//  * everything serves from localhost — EXTERNAL_REQUESTS must stay 0.

function nodeCard(page: Page, title: string) {
  return page
    .locator('[data-testid="spec-node"]')
    .filter({
      has: page.locator('[data-testid="node-title"]', { hasText: new RegExp(`^${title}$`) }),
    })
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

async function runGraph(page: Page): Promise<void> {
  const runResponse = page.waitForResponse(
    (r) => r.url().includes('/api/run') && r.status() === 200,
  );
  await page.getByTestId('run-button').click();
  await runResponse;
}

test('render_math_card renders its MathML card in a sandboxed iframe in the result strip', async ({
  page,
}) => {
  const external = trackExternalRequests(page);
  await page.goto('/');
  await expect(page.getByTestId('flow-canvas')).toBeVisible();

  const card = nodeCard(page, 'render_math_card');

  // Declared + registered → the surface mounts before any run; but the iframe
  // does not exist yet — only the plain-text placeholder (D5 canvas-cost rule).
  await expect(card.getByTestId('render-surface')).toBeVisible();
  const renderer = card.getByTestId('html-card-renderer');
  await expect(renderer).toHaveAttribute('data-renderer-surface', 'card');
  await expect(renderer).toContainText('run to render');
  await expect(card.locator('[data-testid="html-card-frame"]')).toHaveCount(0);

  await runGraph(page);

  // The MathML card now renders inside a FULLY sandboxed iframe: sandbox=""
  // exactly (no allow-scripts), lazy, at the declared height, scroll within.
  const frame = card.getByTestId('html-card-frame');
  await expect(frame).toBeVisible();
  await expect(frame).toHaveAttribute('sandbox', '');
  await expect(frame).toHaveAttribute('loading', 'lazy');
  await expect(frame).toHaveCSS('height', '220px'); // Renderer(..., height=220)

  // The iframe document is the node's own HTML output: title + native MathML.
  const doc = card.frameLocator('[data-testid="html-card-frame"]');
  await expect(doc.locator('h1')).toHaveText('Quadratic roots');
  await expect(doc.locator('math')).toBeVisible();

  // Shell chrome stays shell-owned (D3): header, sockets + handles, widgets.
  await expect(card.getByTestId('node-title')).toHaveText('render_math_card');
  await expect(card.locator('.ge-socket__name', { hasText: 'mathml' })).toBeVisible();
  await expect(card.locator('.ge-handle--in').first()).toBeAttached();
  await expect(card.locator('.ge-handle--out').first()).toBeAttached();
  await expect(card.getByTestId('widget-preview').first()).toBeVisible();

  // The sibling consumers render on their own cards too (one iframe each).
  await expect(
    nodeCard(page, 'table_summary').getByTestId('html-card-frame'),
  ).toHaveAttribute('sandbox', '');
  await expect(
    nodeCard(page, 'dashboard').getByTestId('html-card-frame'),
  ).toHaveAttribute('sandbox', '');

  await page.screenshot({ path: 'tests/__screenshots__/html-card.png', fullPage: false });

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});

test('the results panel mounts the output node html-card with the same sandbox posture (D7)', async ({
  page,
}) => {
  const external = trackExternalRequests(page);
  await page.goto('/');
  await expect(page.getByTestId('flow-canvas')).toBeVisible();

  await runGraph(page);

  // The graph's output node (dashboard) declares html-card → the panel mounts
  // the SAME component with surface="panel"…
  const results = page.getByTestId('run-results');
  const renderer = results.getByTestId('html-card-renderer');
  await expect(renderer).toHaveAttribute('data-renderer-surface', 'panel');
  const frame = results.getByTestId('html-card-frame');
  await expect(frame).toBeVisible();
  await expect(frame).toHaveAttribute('sandbox', '');
  await expect(frame).toHaveCSS('height', '420px'); // Renderer(..., height=420)

  // …showing the composed report, and the old string-iframe special case no
  // longer mounts (one registry, both surfaces, one security posture).
  const doc = results.frameLocator('[data-testid="html-card-frame"]');
  await expect(doc.locator('h1').first()).toHaveText('Widget showcase');
  await expect(page.getByTestId('run-result-frame')).toHaveCount(0);

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});

test('a card that publishes its own height sizes the frame from the run, not the declared config', async ({
  page,
}) => {
  const external = trackExternalRequests(page);
  await page.goto('/?graph=capacity_check');
  await expect(page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]')).toBeVisible({
    timeout: 15_000,
  });

  const card = nodeCard(page, 'calc_card');

  // Before a run there is no per-instance height to read: the placeholder is
  // showing and no iframe exists yet (the D5 canvas-cost rule is unchanged).
  await expect(card.getByTestId('html-card-renderer')).toContainText('run to render');
  await expect(card.locator('[data-testid="html-card-frame"]')).toHaveCount(0);

  // Run and read the height the node itself computed from its row/check counts.
  const runResponse = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname.endsWith('/run') &&
      r.request().method() === 'POST' &&
      r.status() === 200,
  );
  await page.getByTestId('run-button').click();
  const payload: { outputs: Record<string, Record<string, unknown>> } = await (
    await runResponse
  ).json();
  const published = payload.outputs.card.height;
  expect(typeof published).toBe('number');

  const frame = card.getByTestId('html-card-frame');
  await expect(frame).toBeVisible();
  // The surface is the PUBLISHED height, not the spec's declared fallback —
  // this calc has 2 inputs + 2 formulas + 2 described checks, so it is much
  // taller than the static default.
  await expect(frame).toHaveCSS('height', `${published as number}px`);
  expect(published as number).toBeGreaterThan(400);

  // Sizing from outside the frame does not weaken it: sandbox stays exactly "".
  await expect(frame).toHaveAttribute('sandbox', '');

  // The frame really shows the calc card, at a height that fits it: the FAIL
  // verdict in the footer is visible without scrolling the frame.
  const doc = card.frameLocator('[data-testid="html-card-frame"]');
  await expect(doc.locator('.card__title')).toHaveText('Capacity check');
  await expect(doc.locator('.foot')).toBeVisible();

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});
