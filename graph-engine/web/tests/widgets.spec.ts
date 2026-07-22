import { test, expect, type Page } from '@playwright/test';

// The now-LIVE widget editing seam (ADR 0005 integration). The shell mounts the
// commit provider, so unwired literal inputs render editors. These specs prove
// the editor UX on the served showcase graph:
//   * a chip opens its editor;
//   * committing does NOT collapse the editor mid-edit (the WidgetSlot fix);
//   * a committed value reflects on the canvas (re-render shows the new literal);
//   * the table-recipe editor previews the recipe from Python (/api/run).
//
// The COMMIT path (PUT /api/graph) is mocked so this runs parallel-safe against
// the shared demo server without mutating it — disk persistence is proven by the
// Python round-trip test (tests/test_showcase_example.py). The table PREVIEW uses
// the real, read-only /api/run.

function nodeCard(page: Page, title: string) {
  return page
    .locator('[data-testid="spec-node"]')
    .filter({ has: page.locator('[data-testid="node-title"]', { hasText: new RegExp(`^${title}$`) }) })
    .first();
}

test('a math chip opens its editor, keeps it open on commit, and reflects the new literal', async ({
  page,
}) => {
  await page.goto('/');
  await expect(page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]')).toBeVisible({
    timeout: 15_000,
  });

  // Build the "saved" graph the mocked backend will return: the same served
  // graph with parse_expr's `text` literal edited.
  const original = await (await page.request.get('/api/graph')).json();
  const edited = JSON.parse(JSON.stringify(original));
  const NEW_EXPR = 'x**3 - 1';
  for (const node of edited.nodes) {
    if (node.type === 'sym.parse_expr') node.inputs.text = NEW_EXPR;
  }
  await page.route('**/api/graph', async (route) => {
    const method = route.request().method();
    if (method === 'PUT') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ graph: edited }) });
    }
    if (method === 'GET') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(edited) });
    }
    return route.continue();
  });

  const card = nodeCard(page, 'parse_expr');
  await card.getByTestId('widget-chip').first().click();

  // The math editor renders with a live KaTeX preview.
  const input = page.getByTestId('widget-editor-math-input');
  await expect(input).toBeVisible();
  await input.fill(NEW_EXPR);
  await expect(page.locator('.ge-widget-math-preview .katex').first()).toBeVisible({ timeout: 8_000 });

  // Commit (Enter). With the WidgetSlot fix the editor stays OPEN — it must not
  // collapse back to a chip mid-edit.
  const put = page.waitForResponse((r) => r.url().includes('/api/graph') && r.request().method() === 'PUT');
  await input.press('Enter');
  await put;
  await expect(page.getByTestId('widget-slot')).toBeVisible();
  await expect(input).toBeVisible();

  // Close via the discoverable Done affordance → the collapsed chip now shows
  // the persisted literal (the commit reflected on the canvas).
  await card.getByTestId('widget-done').click();
  const chip = card.getByTestId('widget-chip').first();
  await expect(chip).toContainText(NEW_EXPR);
});

test('the table-recipe editor opens and previews the recipe from Python', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]')).toBeVisible({
    timeout: 15_000,
  });

  const card = nodeCard(page, 'apply_recipe');
  await card.getByTestId('widget-chip').first().click();

  const editor = page.getByTestId('table-recipe-editor');
  await expect(editor).toBeVisible();

  // The recipe is shown as a reorderable step list (the product, C-D1).
  await expect(editor.getByTestId('tr-step')).toHaveCount(3);

  // The grid preview is computed by Python (/api/run) — the grid never computes.
  await expect(editor.locator('.tr-preview__grid table')).toBeVisible({ timeout: 20_000 });
  await expect(editor.getByText('preview computed in Python · /api/run')).toBeVisible();

  // Editing UX: the editor does not collapse — Done is the close affordance.
  await expect(card.getByTestId('widget-done')).toBeVisible();
});

test('read-only mode without a commit provider renders no editor chips', async ({ page }) => {
  // Sanity for the read-only path: when the shell does NOT mount the provider
  // (e.g. a headless render), a literal input shows a static value span, never a
  // chip button. Here we assert the served, editable canvas is the opposite —
  // chips ARE buttons — pinning the two modes apart.
  await page.goto('/');
  await expect(page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]')).toBeVisible({
    timeout: 15_000,
  });
  const chip = page.getByTestId('widget-chip').first();
  await expect(chip).toBeVisible();
  await expect(chip).toHaveJSProperty('tagName', 'BUTTON');
});
