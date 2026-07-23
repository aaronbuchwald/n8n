import { test, expect, type Page } from '@playwright/test';

// Node-contextual source editing: clicking a node opens its inspector, and the
// inspector's "Edit source" expands into the source editor for THAT node's
// `@node` function (spec id = the node's type). The old disconnected topbar
// button + node-type dropdown are gone. The editor is honest about scope: it
// is launched from a node but edits the node TYPE's function, so its header
// names the function (module.qualname) + real file path + line range.
//
// The body is a Monaco editor (Python highlighting, fully bundled offline). Its
// content lives in a virtual-scrolled model rather than a <textarea>, so these
// tests read/round-trip through the editor's model (exposed on window.monaco by
// monaco/setup.ts) instead of asserting on a textarea value.

interface MonacoModel {
  getValue(): string;
  setValue(value: string): void;
}
interface MonacoEditorInstance {
  getValue(): string;
  getModel(): MonacoModel | null;
}
interface MonacoBridge {
  editor: { getEditors(): MonacoEditorInstance[] };
}

async function gotoAndSettle(page: Page) {
  await page.goto('/');
  await expect(page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]')).toBeVisible({
    timeout: 15_000,
  });
}

/** Select a node by graph id via its header (a chip click would edit, not inspect). */
async function selectNode(page: Page, nodeId: string) {
  await page.locator(`.react-flow__node[data-id="${nodeId}"] .ge-node__header`).click();
  await expect(page.getByTestId('node-inspector')).toBeVisible();
}

/** Wait for the lazily-loaded Monaco editor to mount and hold the source. */
async function waitForMonaco(page: Page) {
  await expect(page.getByTestId('source-monaco')).toBeVisible();
  await page.waitForFunction(() => {
    const w = window as unknown as { monaco?: MonacoBridge };
    const editors = w.monaco?.editor.getEditors() ?? [];
    return editors.length > 0 && editors[0].getValue().length > 0;
  });
}

/** Read the full source out of Monaco's model (not the virtual-scrolled DOM). */
async function monacoValue(page: Page): Promise<string> {
  return page.evaluate(() => {
    const w = window as unknown as { monaco: MonacoBridge };
    return w.monaco.editor.getEditors()[0].getValue();
  });
}

/** Replace the whole source; setting the model fires the editor's change event. */
async function setMonacoValue(page: Page, value: string) {
  await page.evaluate((next) => {
    const w = window as unknown as { monaco: MonacoBridge };
    w.monaco.editor.getEditors()[0].getModel()?.setValue(next);
  }, value);
}

test('the inspector offers "Edit source" scoped to the clicked node\'s @node function', async ({
  page,
}) => {
  await gotoAndSettle(page);

  // The standalone topbar entry point is gone — source editing starts at a node.
  await expect(page.getByTestId('edit-source-button')).toHaveCount(0);

  // Click the parse_expr node: its inspector offers editing ITS function.
  await selectNode(page, 'expr');
  const inspector = page.getByTestId('node-inspector');
  const editButton = inspector.getByTestId('inspector-edit-source');
  await expect(editButton).toBeEnabled();
  await expect(inspector.getByText('sym.parse_expr').first()).toBeVisible();

  await editButton.click();

  // The editor lives INSIDE the node's inspector panel, pre-scoped to the
  // node's type — no node-type dropdown anywhere.
  const editor = inspector.getByTestId('source-editor');
  await expect(editor).toBeVisible();
  await expect(page.getByTestId('source-spec-select')).toHaveCount(0);
  await expect(editor.getByTestId('source-fn-label')).toHaveText('sym.parse_expr');
  // The real file + line range, so "this edits the real .py" is legible.
  await expect(editor.getByTestId('source-file-label')).toContainText('nodepacks/sym/__init__.py');
  await expect(editor.getByTestId('source-file-label')).toContainText(/lines \d+–\d+/);

  // The Monaco editor is mounted and holds the function source.
  await waitForMonaco(page);
  expect(await monacoValue(page)).toMatch(/def parse_expr/);
  // Python is highlighted: Monaco tokenises into <span class="mtkN"> tokens and
  // the `def` keyword renders inside a token span.
  const tokens = editor.locator('.view-line span[class*="mtk"]');
  expect(await tokens.count()).toBeGreaterThan(1);
  await expect(editor.locator('.view-line').filter({ hasText: 'def parse_expr' })).toBeVisible();

  // Still visibly attached to the clicked node: the inspector header stays.
  await expect(page.getByTestId('inspector-title')).toHaveText('expr · parse_expr');

  // Back returns to the inspector view of the same node.
  await editor.getByTestId('source-back').click();
  await expect(inspector.getByTestId('inspector-inputs')).toBeVisible();

  // Escape steps the surfaces closed one at a time: editor first, then inspector.
  await inspector.getByTestId('inspector-edit-source').click();
  await expect(inspector.getByTestId('source-editor')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(inspector.getByTestId('source-editor')).toHaveCount(0);
  await expect(inspector.getByTestId('inspector-inputs')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('node-inspector')).toHaveCount(0);
});

test('a type shared by several nodes says edits affect them all', async ({ page }) => {
  await gotoAndSettle(page);

  // Two nodes (roots_note, first_note) share sym.describe.
  await selectNode(page, 'roots_note');
  await page.getByTestId('inspector-edit-source').click();
  const note = page.getByTestId('source-shared-note');
  await expect(note).toBeVisible();
  await expect(note).toContainText('all 2 nodes');
});

test('editing a node\'s function, saving, and re-running reflects the change', async ({
  page,
}) => {
  await gotoAndSettle(page);

  // The dashboard node (id "report") is defined in the showcase module itself.
  await selectNode(page, 'report');
  await page.getByTestId('inspector-edit-source').click();
  await waitForMonaco(page);
  expect(await monacoValue(page)).toMatch(/def dashboard/);
  const original = await monacoValue(page);

  const MARKER = '[edited-by-e2e]';
  try {
    // Edit THIS node's function body: stamp a marker into the rendered heading.
    await setMonacoValue(
      page,
      original.replace('{html.escape(title)}', `{html.escape(title)} ${MARKER}`),
    );
    const put = page.waitForResponse(
      (r) => r.url().includes('/api/source/') && r.request().method() === 'PUT',
    );
    await page.getByTestId('source-save-button').click();
    expect((await put).status()).toBe(200);
    await expect(page.getByTestId('source-notice')).toContainText('Saved to');
    await expect(page.getByTestId('source-notice')).toContainText('showcase.py');

    // Re-run: the output card now carries the marker — the edit is live.
    const run = page.waitForResponse(
      (r) => r.url().includes('/api/run') && r.status() === 200,
    );
    await page.getByTestId('run-button').click();
    await run;
    // The dashboard output renders in the panel's html-card frame (ADR 0010
    // 10-K) — the same sandboxed surface the old run-result-frame provided.
    const frame = page
      .getByTestId('run-results')
      .frameLocator('[data-testid="html-card-frame"]');
    await expect(frame.getByText(MARKER)).toBeVisible();
  } finally {
    // Restore the pristine function so the shared demo server (and the repo
    // checkout) is left exactly as found for the other parallel tests.
    const restore = await page.request.put('/api/source/showcase.dashboard', {
      data: { source: original },
    });
    expect(restore.ok()).toBe(true);
  }
});

test('a rejected save (syntax error) surfaces inline and never corrupts the file', async ({
  page,
}) => {
  await gotoAndSettle(page);

  const before = await (await page.request.get('/api/source/sym.parse_expr')).json();

  await selectNode(page, 'expr');
  await page.getByTestId('inspector-edit-source').click();
  await waitForMonaco(page);
  expect(await monacoValue(page)).toMatch(/def parse_expr/);

  await setMonacoValue(page, 'def parse_expr(: this does not parse');
  const put = page.waitForResponse(
    (r) => r.url().includes('/api/source/') && r.request().method() === 'PUT',
  );
  await page.getByTestId('source-save-button').click();
  expect((await put).status()).toBe(400);

  // The error is inline in the node's panel; the editor stays open for fixing.
  const error = page.getByTestId('source-error');
  await expect(error).toBeVisible();
  await expect(error).toContainText('does not parse');
  await expect(page.getByTestId('source-monaco')).toBeVisible();

  // The real file is untouched.
  const after = await (await page.request.get('/api/source/sym.parse_expr')).json();
  expect(after.source).toBe(before.source);
});

test('a node with no matching spec disables "Edit source" with a reason', async ({ page }) => {
  // Serve the real graph plus one node whose type has no spec.
  const original = await (await page.request.get('/api/graph')).json();
  const withGhost = {
    ...original,
    nodes: [
      ...original.nodes,
      { id: 'ghost', type: 'nope.missing', inputs: {}, position: null },
    ],
  };
  await page.route('**/api/graph', async (route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(withGhost),
      });
    }
    return route.continue();
  });

  // The extra node auto-lays-out into the bottom-right corner, where the
  // default 1280px viewport (minus the W5 palette rail) puts it under the
  // minimap — widen so its header stays clickable.
  await page.setViewportSize({ width: 1600, height: 900 });
  await gotoAndSettle(page);
  await selectNode(page, 'ghost');
  const editButton = page.getByTestId('inspector-edit-source');
  await expect(editButton).toBeDisabled();
  await expect(page.getByText('unknown type — no source')).toBeVisible();
});
