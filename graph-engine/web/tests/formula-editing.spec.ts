import { test, expect, type Page, type Locator } from '@playwright/test';
import { readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// ADR 0018 — formula editing. The observable contract (D7 1–8) for editing
// `sheet.calc_card`'s multi-line calc literals in the inspector, against the
// LIVE demo server on the capacity_check graph (no mocks):
//
//  1. the `formulas` literal is edited as MULTI-LINE text and a new
//     `expr  # reference` entry round-trips verbatim into the real `.py`;
//  2. Enter inserts a newline and NEVER commits (D5);
//  3. an editable row shows no second, uneditable copy of its own value —
//     while an OUTPUT row keeps the scrollable/copyable block (D1);
//  4. the mini-syntax is on the surface: placeholder + format hint;
//  5. the preview renders each entry as its ANATOMY — typeset expression,
//     unit chip, reference gutter — instead of falling back to raw text (D2/D4);
//  6. `formulas` gets live, line-numbered `parse_formulas` errors and an
//     invalid draft is refused, leaving the file untouched;
//  7. symbol chips forecast the socket set, and committing reshapes the real
//     sockets, pruning a wired edge with a toast;
//  8. the Tier-1 floor: any plain `str` param whose committed value contains a
//     newline is edited in a textarea with the same keyboard rules.
//
// These tests REALLY rewrite examples/capacity_check/capacity_check.py through
// the server and restore the pristine graph + bytes in a finally; the spec runs
// in its own sequenced project (see playwright.config.ts) because it owns that
// workspace while it runs.

test.describe.configure({ mode: 'serial' });
test.use({ permissions: ['clipboard-read', 'clipboard-write'] });

const HERE = path.dirname(fileURLToPath(import.meta.url));
const MODULE_PY = path.resolve(HERE, '..', '..', 'examples', 'capacity_check', 'capacity_check.py');
const GRAPH_ROUTE = '/api/graphs/capacity_check/graph';

// The literal capacity_check.py authors — two entries, each with a `# reference`,
// the second carrying a trailing `[unit]`.
const ORIGINAL_FORMULAS =
  'r = F_max / C_min  # demand / capacity\nU = 100 * r [%]  # utilisation';
const ORIGINAL_CHECKS = 'U < 100  # capacity not exceeded\nU < 50  # utilisation target';

interface ServedGraph {
  nodes: Array<{ id: string; type: string; inputs: Record<string, unknown> }>;
  edges: Array<{ target: string; targetInput: string }>;
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

/** Open the capacity graph and select the `card` node (the calc_card instance). */
async function openCard(page: Page): Promise<Locator> {
  await page.goto('/?graph=capacity_check');
  await expect(page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]')).toBeVisible({
    timeout: 15_000,
  });
  await page.locator('.react-flow__node[data-id="card"] [data-testid="node-title"]').click();
  const inspector = page.getByTestId('node-inspector');
  await expect(inspector).toBeVisible();
  return inspector;
}

function inputRow(page: Page, inspector: Locator, socket: string): Locator {
  return inspector
    .locator('[data-testid="inspector-input"]')
    .filter({ has: page.locator('.ge-inspector__socket', { hasText: new RegExp(`^${socket}$`) }) });
}

function outputRow(page: Page, inspector: Locator, socket: string): Locator {
  return inspector
    .locator('[data-testid="inspector-output"]')
    .filter({ has: page.locator('.ge-inspector__socket', { hasText: new RegExp(`^${socket}$`) }) });
}

const servedGraph = async (page: Page): Promise<ServedGraph> =>
  (await (await page.request.get(GRAPH_ROUTE)).json()) as ServedGraph;

const cardInput = (graph: ServedGraph, name: string): unknown =>
  graph.nodes.find((n) => n.id === 'card')?.inputs[name];

/** Snapshot the pristine graph + module bytes; restore both however the test ends. */
async function withRestore(page: Page, body: () => Promise<void>): Promise<void> {
  const original = await servedGraph(page);
  const moduleBefore = readFileSync(MODULE_PY, 'utf8');
  try {
    await body();
  } finally {
    const res = await page.request.put(GRAPH_ROUTE, { data: { graph: original } });
    expect(res.ok()).toBe(true);
    // …then the pristine BYTES: writeback canonicalizes quoting/spacing, and the
    // server re-reads the module per request, so restoring the authored text is
    // safe and keeps the repo clean across runs.
    writeFileSync(MODULE_PY, moduleBefore);
  }
}

test('D7-1/2/3: multi-line editing round-trips a referenced entry into the .py, Enter never commits, and the editable row shows no duplicate value box', async ({
  page,
}) => {
  test.setTimeout(120_000);
  const puts = trackGraphPuts(page);
  const inspector = await openCard(page);

  await withRestore(page, async () => {
    const row = inputRow(page, inspector, 'formulas');
    const editor = row.getByTestId('widget-editor-calc-input');

    // 1. The editor is a real multi-line textarea holding the newline verbatim.
    await expect(row.getByTestId('inspector-widget-slot')).toHaveAttribute('data-input', 'formulas');
    await expect(editor).toHaveJSProperty('tagName', 'TEXTAREA');
    await expect(editor).toHaveValue(ORIGINAL_FORMULAS);
    expect(await editor.inputValue()).toContain('\n');

    // 3. No second, uneditable copy of the literal on the editable row — and no
    //    "no value yet" placeholder under the editor either.
    await expect(row.getByTestId('inspector-value')).toHaveCount(0);
    await expect(row).not.toContainText('no value yet');

    // 2. Enter is a NEWLINE: the draft grows a line and nothing is saved.
    const putsBeforeEnter = puts.count();
    await editor.click();
    await editor.press('Control+End');
    await editor.press('Enter');
    await expect(editor).toHaveValue(`${ORIGINAL_FORMULAS}\n`);
    await page.waitForTimeout(800); // a commit would have PUT by now
    expect(puts.count()).toBe(putsBeforeEnter);
    // Un-saved: the server still holds the two-entry literal.
    expect(cardInput(await servedGraph(page), 'formulas')).toBe(ORIGINAL_FORMULAS);

    // 1. Add a third entry WITH a reference and apply with Control+Enter.
    const withMargin = `${ORIGINAL_FORMULAS}\nm = C_min - F_max  # margin over demand`;
    await editor.fill(withMargin);
    const commit = waitForGraphPut(page);
    await editor.press('Control+Enter');
    await commit;

    // The literal round-tripped byte for byte — newline included — into the
    // served graph AND into the real module the server rewrote.
    await expect
      .poll(async () => cardInput(await servedGraph(page), 'formulas'), { timeout: 10_000 })
      .toBe(withMargin);
    const rewritten = readFileSync(MODULE_PY, 'utf8');
    expect(rewritten).toContain('m = C_min - F_max  # margin over demand');
    // ADR 0020 D1: the multi-line value is written back as parenthesized
    // implicit concatenation — one repr()-escaped fragment per calc entry, each
    // carrying its own `\n` — NOT one physical line of escaped newlines.
    expect(rewritten).toContain(
      "        formulas=(\n" +
        "            'r = F_max / C_min  # demand / capacity\\n'\n" +
        "            'U = 100 * r [%]  # utilisation\\n'\n" +
        "            'm = C_min - F_max  # margin over demand'\n" +
        '        ),\n',
    );
    expect(rewritten).not.toContain(`formulas='${withMargin.replace(/\n/g, '\\n')}'`);

    // D3: because one argument went block form, the WHOLE call is expanded —
    // one argument per line, trailing comma, closing paren at statement indent.
    expect(rewritten).toContain(
      '    card = calc_card(\n' +
        "        title='Capacity check',\n" +
        "        as_of='2026-07-24',\n" +
        '        formulas=(\n' +
        "            'r = F_max / C_min  # demand / capacity\\n'\n" +
        "            'U = 100 * r [%]  # utilisation\\n'\n" +
        "            'm = C_min - F_max  # margin over demand'\n" +
        '        ),\n' +
        '        checks=(\n' +
        "            'U < 100  # capacity not exceeded\\n'\n" +
        "            'U < 50  # utilisation target'\n" +
        '        ),\n' +
        '        F_max=F_max,\n' +
        '        C_min=C_min,\n' +
        '    )\n',
    );
    // No triple-quoted block was introduced: the argument stays a plain literal.
    expect(rewritten).not.toContain('formulas="""');

    // Still exactly one surface for that value after the commit.
    await expect(row.getByTestId('inspector-value')).toHaveCount(0);
  });
});

test('D7-3: an output row keeps the scrollable, copyable value block', async ({ page }) => {
  test.setTimeout(120_000);
  const inspector = await openCard(page);

  // Run so the card's `result` output has its HTML document to show.
  const runResponse = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname.endsWith('/run') &&
      r.request().method() === 'POST' &&
      r.status() === 200,
  );
  await page.getByTestId('run-button').click();
  await runResponse;

  const row = outputRow(page, inspector, 'result');
  const value = row.getByTestId('inspector-value');
  await expect(value).toBeVisible({ timeout: 15_000 });
  const full = (await value.textContent()) ?? '';
  expect(full).toContain('<!doctype html>');
  expect(full).not.toContain('…');

  await value.hover();
  await row.getByTestId('inspector-value-copy').click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(full);

  // …while the editable literal rows next to it still show only their editors,
  // even now that a run value exists (it equals the literal — D1).
  await expect(inputRow(page, inspector, 'formulas').getByTestId('inspector-value')).toHaveCount(0);
  await expect(inputRow(page, inspector, 'checks').getByTestId('inspector-value')).toHaveCount(0);
});

test('D7-4/5: the syntax is on the surface — hint, placeholder, and a preview that renders each entry as its anatomy', async ({
  page,
}) => {
  test.setTimeout(120_000);
  const inspector = await openCard(page);

  await withRestore(page, async () => {
    const formulas = inputRow(page, inspector, 'formulas');
    const checks = inputRow(page, inspector, 'checks');

    // 4. The persistent format hint teaches the three fields and the keys.
    const hint = formulas.getByTestId('calc-format-hint');
    await expect(hint).toBeVisible();
    await expect(hint).toContainText('one entry per line');
    await expect(hint).toContainText('# text = reference');
    await expect(hint).toContainText('trailing [unit] = display unit');
    await expect(hint).toContainText('⌘/Ctrl+Enter');

    // 4. The empty `checks` editor shows the syntax skeleton as its placeholder.
    const checksEditor = checks.getByTestId('widget-editor-calc-input');
    await expect(checksEditor).toHaveValue(ORIGINAL_CHECKS);
    await expect(checksEditor).toHaveAttribute('placeholder', 'expression  # description');
    await checksEditor.fill('');
    await expect(checksEditor).toHaveValue('');
    await expect(checksEditor).toHaveAttribute('placeholder', 'expression  # description');
    // `checks` is not the deriving param: no chips row, plain multi-line commit.
    await expect(checks.getByTestId('calc-sockets')).toHaveCount(0);
    await checksEditor.fill(ORIGINAL_CHECKS); // leave the draft as authored

    // 5. `U = 100 * r [%]  # utilisation` renders as ITS ANATOMY: typeset math,
    //    a `%` unit chip, and `utilisation` in the reference gutter — the `#`
    //    and `[…]` no longer force the raw-text fallback.
    const second = formulas.getByTestId('calc-preview-row').nth(1);
    await expect(second).toHaveAttribute('data-line', '2');
    await expect(second).toHaveAttribute('data-fallback', 'false');
    await expect(second.locator('.katex')).toHaveCount(1);
    await expect(second.getByTestId('calc-preview-unit')).toHaveText('%');
    await expect(second.getByTestId('calc-preview-ref')).toHaveText('utilisation');
    // The reference is NOT left inside the typeset expression.
    await expect(second.locator('.katex')).not.toContainText('utilisation');

    // The first entry has a reference but no unit — the unit slot simply absent.
    const first = formulas.getByTestId('calc-preview-row').first();
    await expect(first).toHaveAttribute('data-line', '1');
    await expect(first.getByTestId('calc-preview-ref')).toHaveText('demand / capacity');
    await expect(first.getByTestId('calc-preview-unit')).toHaveCount(0);

    // Typing a reference moves it into the gutter live — the syntax lesson.
    const editor = formulas.getByTestId('widget-editor-calc-input');
    await editor.fill(`${ORIGINAL_FORMULAS}\nm = C_min - F_max  # margin over demand`);
    const third = formulas.getByTestId('calc-preview-row').nth(2);
    await expect(third).toHaveAttribute('data-line', '3');
    await expect(third.getByTestId('calc-preview-ref')).toHaveText('margin over demand');
    await expect(third).toHaveAttribute('data-fallback', 'false');
  });
});

test('D7-6: an invalid formulas draft shows the server line-numbered error and is refused', async ({
  page,
}) => {
  test.setTimeout(120_000);
  const puts = trackGraphPuts(page);
  const inspector = await openCard(page);

  await withRestore(page, async () => {
    const editor = inputRow(page, inspector, 'formulas').getByTestId('widget-editor-calc-input');
    await editor.fill(`${ORIGINAL_FORMULAS}\nthis entry has no equals sign`);

    const error = page.getByTestId('calc-derive-error');
    await expect(error).toBeVisible({ timeout: 15_000 });
    // Python's own message, naming the line and restating the rule.
    await expect(error).toHaveText(/formulas line \d+/);
    await expect(error).toContainText("has no '='");

    const putsBefore = puts.count();
    await editor.press('Control+Enter'); // apply anyway
    await expect(error).toBeVisible();
    await page.waitForTimeout(900); // a commit would have PUT by now
    expect(puts.count()).toBe(putsBefore);
    // Draft retained in the textarea; the file untouched.
    expect(await editor.inputValue()).toContain('this entry has no equals sign');
    expect(cardInput(await servedGraph(page), 'formulas')).toBe(ORIGINAL_FORMULAS);
  });
});

test('D7-7: chips forecast the socket set, and committing reshapes the real sockets and prunes a wired edge with a toast', async ({
  page,
}) => {
  test.setTimeout(120_000);
  const puts = trackGraphPuts(page);
  const inspector = await openCard(page);
  const chip = (symbol: string) =>
    page.locator(`[data-testid="calc-symbol-chip"][data-symbol="${symbol}"]`);
  const socket = (name: string) =>
    page.locator(`.react-flow__node[data-id="card"] .ge-socket__name[title="${name}"]`);

  await withRestore(page, async () => {
    const editor = inputRow(page, inspector, 'formulas').getByTestId('widget-editor-calc-input');
    // The formulas' free symbols are already the node's derived sockets.
    await expect(socket('F_max')).toBeVisible();
    await expect(socket('C_min')).toBeVisible();

    // A new free symbol chips up BEFORE any commit; nothing is saved by typing.
    const putsBeforeTyping = puts.count();
    await editor.fill(`${ORIGINAL_FORMULAS}\nm = C_min - F_max + q  # margin`);
    await expect(chip('q')).toHaveAttribute('data-state', 'added', { timeout: 15_000 });
    await expect(chip('F_max')).toHaveAttribute('data-state', 'kept');
    expect(puts.count()).toBe(putsBeforeTyping);
    await expect(socket('q')).toHaveCount(0);

    // Dropping a WIRED symbol forecasts the unwiring, still before any commit.
    await editor.fill('r = 100 / C_min  # demand / capacity\nU = 100 * r [%]  # utilisation');
    await expect(chip('F_max')).toHaveAttribute('data-state', 'removed', { timeout: 15_000 });
    await expect(chip('F_max')).toContainText('will unwire');

    // Applying reconciles the real sockets and prunes the edge in the SAME save.
    const commit = waitForGraphPut(page);
    await editor.press('Control+Enter');
    await commit;
    const toast = page.getByTestId('calc-toast');
    await expect(toast).toBeVisible({ timeout: 10_000 });
    await expect(toast).toContainText('F_max removed from equation — unwired from');
    await expect(socket('F_max')).toHaveCount(0);
    await expect(socket('C_min')).toBeVisible();

    const after = await servedGraph(page);
    expect(after.edges.some((e) => e.target === 'card' && e.targetInput === 'F_max')).toBe(false);
    expect(after.edges.some((e) => e.target === 'card' && e.targetInput === 'C_min')).toBe(true);
  });
});

test('D7-8: a plain str param whose value holds a newline is edited in a textarea with the same keyboard rules', async ({
  page,
}) => {
  test.setTimeout(120_000);
  const puts = trackGraphPuts(page);
  await page.goto('/?graph=capacity_check');
  await expect(page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]')).toBeVisible({
    timeout: 15_000,
  });

  await withRestore(page, async () => {
    // `title` is a plain `str` with the type-derived `text` widget — no node-side
    // declaration. Seed a multi-line literal through the graph API, exactly as a
    // hand-edited source would carry one, then reload and edit it in the UI.
    const graph = await servedGraph(page);
    const card = graph.nodes.find((n) => n.id === 'card');
    expect(card).toBeDefined();
    card!.inputs.title = 'Capacity check\nrevision B';
    expect((await page.request.put(GRAPH_ROUTE, { data: { graph } })).ok()).toBe(true);

    await page.reload();
    await expect(page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]')).toBeVisible({
      timeout: 15_000,
    });
    await page.locator('.react-flow__node[data-id="card"] [data-testid="node-title"]').click();
    const inspector = page.getByTestId('node-inspector');
    const row = inputRow(page, inspector, 'title');

    // Content-promoted: the textarea, NOT the single-line input it would
    // otherwise be (which cannot even display the second line).
    const editor = row.getByTestId('widget-editor-text-multiline');
    await expect(editor).toBeVisible({ timeout: 15_000 });
    await expect(editor).toHaveJSProperty('tagName', 'TEXTAREA');
    await expect(row.getByTestId('widget-editor-text')).toHaveCount(0);
    await expect(editor).toHaveValue('Capacity check\nrevision B');
    // D1 applies to the generic floor too: one surface, no read-only twin.
    await expect(row.getByTestId('inspector-value')).toHaveCount(0);

    // Enter inserts a newline and commits nothing…
    const putsBeforeEnter = puts.count();
    await editor.click();
    await editor.press('Control+End');
    await editor.press('Enter');
    await editor.pressSequentially('revision C');
    await expect(editor).toHaveValue('Capacity check\nrevision B\nrevision C');
    await page.waitForTimeout(800);
    expect(puts.count()).toBe(putsBeforeEnter);

    // …Control+Enter does, and the three-line literal lands in the source.
    const commit = waitForGraphPut(page);
    await editor.press('Control+Enter');
    await commit;
    await expect
      .poll(async () => cardInput(await servedGraph(page), 'title'), { timeout: 10_000 })
      .toBe('Capacity check\nrevision B\nrevision C');
    // The rule is value-driven (ADR 0020 D2): a newline in ANY str param — a
    // plain `title` included — lands as the block form, not an escaped one-liner.
    const rewritten = readFileSync(MODULE_PY, 'utf8');
    expect(rewritten).toContain(
      '        title=(\n' +
        "            'Capacity check\\n'\n" +
        "            'revision B\\n'\n" +
        "            'revision C'\n" +
        '        ),\n',
    );
    expect(rewritten).not.toContain("title='Capacity check\\nrevision B\\nrevision C'");
  });
});

// The editor IS the copy surface. Removing the duplicate read-only box (D7-3)
// must not cost the copy affordance — and it must copy what is IN the box,
// including uncommitted edits, not the last committed literal.
test('the formulas editor carries copy-on-hover and copies its live content', async ({ page }) => {
  const inspector = await openCard(page);
  const row = inputRow(page, inspector, 'formulas');
  const editor = row.getByTestId('widget-editor-calc-input');
  await expect(editor).toBeVisible();

  // No second box was reintroduced to carry the button.
  await expect(row.getByTestId('inspector-value')).toHaveCount(0);

  const copy = row.getByTestId('inspector-value-copy');
  await expect(copy).toHaveCount(1);
  // Hidden at rest, revealed on hover — an affordance, not permanent chrome.
  await expect(copy).toHaveCSS('opacity', '0');
  await row.getByTestId('widget-editor-calc-input').hover();
  await expect(copy).toHaveCSS('opacity', '1');

  // It copies the LIVE draft: type without committing, then copy.
  const drafted = 'r = F_max / C_min  # demand / capacity\nU = 100 * r [%]  # utilisation\nm = C_min - F_max  # margin';
  await editor.fill(drafted);
  await copy.click();
  await expect(copy).toHaveAttribute('data-copied', 'true');
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(drafted);

  // Nothing was committed by copying — the editor still holds the draft.
  await expect(editor).toHaveValue(drafted);
});
