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
//  * a card taller than its frame (`sheet.calc_card` on capacity_check) keeps
//    the DECLARED config height and scrolls its content inside the frame — a
//    scriptless iframe cannot measure itself, and a pixel height is
//    presentation, so it never enters the node's dataflow contract (ADR 0019);
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

test('a card frame uses its DECLARED height and taller content stays reachable inside it', async ({
  page,
}) => {
  const external = trackExternalRequests(page);

  // The declared height is the node type's own renderer config — read it from
  // the served spec rather than restating a number the pack owns.
  const served: { specs: Record<string, { renderer: { config: Record<string, unknown> } }> } =
    await (await page.request.get('/api/specs')).json();
  const declared = served.specs['sheet.calc_card'].renderer.config.height;
  expect(typeof declared).toBe('number');

  await page.goto('/?graph=capacity_check');
  await expect(page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]')).toBeVisible({
    timeout: 15_000,
  });

  const card = nodeCard(page, 'calc_card');

  // Before a run there is nothing to show: the placeholder is showing and no
  // iframe exists yet (the D5 canvas-cost rule is unchanged).
  await expect(card.getByTestId('html-card-renderer')).toContainText('run to render');
  await expect(card.locator('[data-testid="html-card-frame"]')).toHaveCount(0);

  const runResponse = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname.endsWith('/run') &&
      r.request().method() === 'POST' &&
      r.status() === 200,
  );
  await page.getByTestId('run-button').click();
  // ONE output: the card document itself — a pixel height is presentation, so
  // it is not published as a socket (the node's whole output IS the string).
  const payload: { outputs: Record<string, Record<string, unknown>> } = await (
    await runResponse
  ).json();
  expect(typeof payload.outputs.card.result).toBe('string');

  const frame = card.getByTestId('html-card-frame');
  await expect(frame).toBeVisible();
  // The surface is the node type's DECLARED height — a scriptless iframe cannot
  // measure itself, so nothing about the frame's size comes from the run.
  await expect(frame).toHaveCSS('height', `${declared as number}px`);
  // Fixing the size from outside does not weaken the frame: sandbox stays "".
  await expect(frame).toHaveAttribute('sandbox', '');

  // This calc is taller than the declared frame, and none of it is lost: the
  // document scrolls INSIDE the frame, so the FAIL verdict in the footer is
  // reachable.
  const doc = card.frameLocator('[data-testid="html-card-frame"]');
  await expect(doc.locator('.card__title')).toHaveText('Capacity check');
  // The whole document is there — the footer verdict is the LAST thing in it.
  await expect(doc.locator('.foot')).toContainText('Overall');
  // …and the overflow is scrollable, not clipped: the content is taller than
  // the frame and the document can actually be scrolled to reach it.
  const handle = await frame.elementHandle();
  const content = await handle?.contentFrame();
  expect(content).not.toBeNull();
  const scroll = await content!.evaluate(() => {
    const el = document.scrollingElement;
    if (el === null) return null;
    el.scrollTop = el.scrollHeight;
    return { overflow: el.scrollHeight - el.clientHeight, scrolled: el.scrollTop };
  });
  expect(scroll).not.toBeNull();
  expect(scroll!.overflow).toBeGreaterThan(0);
  expect(scroll!.scrolled).toBeGreaterThan(0);

  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});
