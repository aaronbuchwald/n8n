import { test, expect, type Page } from '@playwright/test';
import { hasUnsupportedShape, sympyToLatex } from '../src/widgets/math/translate';

// UI review 0005 #4, #10, #17 — the math widget's live preview.
//
// #4: the sympy->LaTeX mini-translator renders some valid SymPy WRONG but
// confidently (`x**(y+1)`, `2**x**2`, nested `sqrt(sqrt(x))`). These cases
// pin the detector: it must trigger on exactly the shapes the review caught,
// and stay silent on the good inputs the mini-translator already handles
// (including the exact expressions used elsewhere in the widget suite, so a
// regression here would also break `tests/widgets.spec.ts`).
test.describe('hasUnsupportedShape (review #4 detection rule)', () => {
  const badInputs: Array<[string, string]> = [
    ['x**(y+1)', 'grouped exponent'],
    ['2**x**2', 'chained exponentiation'],
    ['sqrt(sqrt(x))', 'nested function call'],
    ['x**sqrt(y)', 'function call as exponent'],
  ];

  for (const [expr, why] of badInputs) {
    test(`flags "${expr}" (${why})`, () => {
      expect(hasUnsupportedShape(expr)).toBe(true);
    });
  }

  const goodInputs = [
    'x**2',
    'sqrt(x)',
    'pi',
    'x*y',
    'a = b + c',
    'x**3 - 1', // used by tests/widgets.spec.ts
    'x**2 - 5*x + 6', // the "good" value from review #10's repro
    '(x+1)**2',
    'sqrt(x)**2',
    'sqrt(x + y)',
  ];

  for (const expr of goodInputs) {
    test(`does not flag "${expr}"`, () => {
      expect(hasUnsupportedShape(expr)).toBe(false);
    });
  }

  test('good inputs still translate to sane LaTeX', () => {
    expect(sympyToLatex('x**2')).toBe('x^{2}');
    expect(sympyToLatex('sqrt(x)')).toBe('\\sqrt{x}');
    expect(sympyToLatex('pi')).toBe('\\pi');
    expect(sympyToLatex('x*y')).toBe('x \\cdot y');
  });
});

function nodeCard(page: Page, title: string) {
  return page
    .locator('[data-testid="spec-node"]')
    .filter({ has: page.locator('[data-testid="node-title"]', { hasText: new RegExp(`^${title}$`) }) })
    .first();
}

// ADR 0013: editing moved to the inspector. The math editor now lives in the
// inspector's widget slot, so scope every query to it (the card also mounts a
// read-only `widget-math-preview` block, so an unscoped query is ambiguous).
async function openMathEditor(page: Page) {
  await page.goto('/');
  await expect(page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]')).toBeVisible({
    timeout: 15_000,
  });
  await nodeCard(page, 'parse_expr').getByTestId('node-title').click();
  const inspector = page.getByTestId('node-inspector');
  await expect(inspector).toBeVisible();
  const input = inspector.getByTestId('widget-editor-math-input');
  await expect(input).toBeVisible();
  return { input, inspector };
}

test('a shape the mini-translator cannot faithfully render falls back to a labelled raw preview (#4)', async ({
  page,
}) => {
  const { input, inspector } = await openMathEditor(page);
  await input.fill('x**(y+1)');

  const preview = inspector.getByTestId('widget-math-preview');
  const cue = inspector.getByTestId('widget-math-fallback-cue');
  await expect(cue).toBeVisible({ timeout: 8_000 });
  await expect(cue).toContainText(/approximate|can.t typeset/i);

  // The raw expression is shown verbatim (not a mistranslated KaTeX render).
  await expect(preview).toContainText('x**(y+1)');
  await expect(preview.locator('.katex')).toHaveCount(0);
});

test('a good expression still renders live KaTeX with no fallback cue (#4)', async ({ page }) => {
  const { input, inspector } = await openMathEditor(page);
  await input.fill('x**3 - 1');

  await expect(inspector.locator('.ge-widget-math-preview .katex').first()).toBeVisible({ timeout: 8_000 });
  await expect(inspector.getByTestId('widget-math-fallback-cue')).toHaveCount(0);
});

test('a stale in-flight render never clobbers a later draft (#10)', async ({ page }) => {
  const { input, inspector } = await openMathEditor(page);

  // Type an unsupported shape (resolves synchronously to the fallback), then
  // immediately overwrite with a good expression. Without the `previewSeq`
  // guard a slow/earlier resolution could land after the later one and show
  // stale content under the current draft.
  await input.fill('sqrt(sqrt(x))');
  await input.fill('x**2');

  await expect(inspector.locator('.ge-widget-math-preview .katex').first()).toBeVisible({ timeout: 8_000 });
  await expect(inspector.getByTestId('widget-math-fallback-cue')).toHaveCount(0);
  await expect(inspector.getByTestId('widget-math-preview')).not.toContainText('sqrt(sqrt(x))');
});
