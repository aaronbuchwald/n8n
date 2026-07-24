import { test, expect, type Page } from '@playwright/test';

// The inspector's value fields render the COMPLETE value (never a truncated
// preview): input values, output values, and the call-site source all show in a
// scrollable block with a hover/focus copy button and — when the value is tall —
// a "Show more" toggle that grows the field. These assertions are READ-ONLY on
// the graph (load + run + inspect), so the spec is parallel-safe in `chromium`.
//
// Clipboard reads need explicit permission; 127.0.0.1 is a secure context in
// Chromium, so navigator.clipboard works once granted.
test.use({ permissions: ['clipboard-read', 'clipboard-write'] });

async function gotoHandcalcDemo(page: Page) {
  await page.goto('/?graph=handcalc_demo');
  await expect(page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]')).toBeVisible({
    timeout: 15_000,
  });
}

async function runGraph(page: Page) {
  // The app posts to the SCOPED run route (/api/graphs/<id>/run), which has no
  // "/api/run" substring — match a POST whose path ends in /run instead.
  const runResponse = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname.endsWith('/run') &&
      r.request().method() === 'POST' &&
      r.status() === 200,
  );
  await page.getByTestId('run-button').click();
  await runResponse;
  await expect(page.getByTestId('run-results')).toBeVisible();
}

/** Select the `steps` (handcalc) node via its header — a chip click would edit. */
async function selectSteps(page: Page) {
  await page.locator('.react-flow__node[data-id="steps"] .ge-node__header').click();
  await expect(page.getByTestId('node-inspector')).toBeVisible();
}

function outputRow(page: Page, socket: string) {
  return page
    .getByTestId('node-inspector')
    .getByTestId('inspector-output')
    .filter({ has: page.locator('.ge-inspector__socket', { hasText: new RegExp(`^${socket}$`) }) });
}

function inputRow(page: Page, socket: string) {
  return page
    .getByTestId('node-inspector')
    .getByTestId('inspector-input')
    .filter({ has: page.locator('.ge-inspector__socket', { hasText: new RegExp(`^${socket}$`) }) });
}

async function readClipboard(page: Page): Promise<string> {
  return page.evaluate(() => navigator.clipboard.readText());
}

test('the inspector shows the full latex output, not a truncated preview, and copies it verbatim', async ({
  page,
}) => {
  await gotoHandcalcDemo(page);
  await runGraph(page);
  await selectSteps(page);

  const row = outputRow(page, 'latex');
  const value = row.getByTestId('inspector-value');
  await expect(value).toBeVisible();

  // The COMPLETE handcalcs latex blob is in the DOM — the aligned environment's
  // opening AND closing are both present, and there is no truncation ellipsis.
  const full = (await value.textContent()) ?? '';
  expect(full).toContain('\\begin{aligned}');
  expect(full).toContain('\\end{aligned}');
  expect(full).not.toContain('…');
  expect(full.length).toBeGreaterThan(120);

  // The copy button (revealed on hover) copies the FULL raw value.
  await value.hover();
  const copy = row.getByTestId('inspector-value-copy');
  await copy.click();
  await expect(copy).toHaveText('Copied ✓');
  expect(await readClipboard(page)).toBe(full);
});

test('a long value block can be expanded to show more', async ({ page }) => {
  await gotoHandcalcDemo(page);
  await runGraph(page);
  await selectSteps(page);

  const row = outputRow(page, 'latex');
  const value = row.getByTestId('inspector-value');
  const toggle = row.getByTestId('inspector-value-toggle');

  // The latex blob overflows the collapsed cap, so the toggle is offered.
  await expect(toggle).toHaveText('Show more');
  const collapsed = await value.boundingBox();

  await toggle.click();
  await expect(toggle).toHaveText('Show less');
  await expect(value).toHaveAttribute('data-expanded', 'true');

  const expanded = await value.boundingBox();
  expect(expanded).not.toBeNull();
  expect(collapsed).not.toBeNull();
  expect(expanded!.height).toBeGreaterThan(collapsed!.height);
});

test('a read-only input value block copies its full value too', async ({ page }) => {
  await gotoHandcalcDemo(page);
  await runGraph(page);
  await selectSteps(page);

  // Re-targeted per ADR 0018 D1: an EDITABLE row is now just its editor (the
  // `lines` calc textarea), so the value block it used to duplicate is gone.
  // The behavior this test proves — full value + verbatim copy — lives
  // unchanged on read-only rows, e.g. the WIRED `C_min` socket, whose value
  // exists nowhere else in the row.
  const row = inputRow(page, 'C_min');
  await expect(row.locator('.ge-inspector__tag--wired')).toBeVisible();
  const value = row.getByTestId('inspector-value');
  await expect(value).toBeVisible();
  const full = (await value.textContent()) ?? '';
  expect(full.length).toBeGreaterThan(0);

  await value.hover();
  await row.getByTestId('inspector-value-copy').click();
  expect(await readClipboard(page)).toBe(full);

  // …and the editable row it moved off really has no second, uneditable copy.
  const linesRow = inputRow(page, 'lines');
  await expect(linesRow.getByTestId('widget-editor-calc-input')).toBeVisible();
  await expect(linesRow.getByTestId('inspector-value')).toHaveCount(0);
});

test('the call-site source block shows and copies the full statement', async ({ page }) => {
  await gotoHandcalcDemo(page);
  await selectSteps(page);

  const callsite = page.getByTestId('inspector-callsite');
  const source = callsite.getByTestId('callsite-source');
  await expect(source).toBeVisible();
  const full = (await source.textContent()) ?? '';
  expect(full.length).toBeGreaterThan(0);

  await source.hover();
  await callsite.getByTestId('inspector-value-copy').click();
  expect(await readClipboard(page)).toBe(full);
});
