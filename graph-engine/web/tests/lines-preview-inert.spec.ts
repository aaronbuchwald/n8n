import { test, expect, type Page } from '@playwright/test';

// Regression for the reported "clicking the lines preview brings up a garbage
// link" on handcalc_demo's handcalc node (graph id `steps`). The `lines` calc
// literal (`margin = C_min - F_max`) renders as a READ-ONLY card preview
// (ADR 0013 D2, block strip). The contract that must hold:
//
//   * the preview is inert: it contains no anchor/`href`, and clicking its body
//     never navigates / opens a popup — it just selects the node and opens the
//     inspector like any other card region;
//   * the shared KaTeX loader pins `trust: false`, so even a calc line that
//     smuggles raw `\href` (the translators forward unknown LaTeX verbatim) can
//     never become a live `<a>` "link out of the formula";
//   * the equation still typesets (KaTeX) or falls back to honest raw text;
//   * everything serves from localhost — no external request escapes.

const stepsNode = (page: Page) => page.locator('.react-flow__node[data-id="steps"]');
const calcPreview = (page: Page) =>
  stepsNode(page).locator('[data-testid="widget-preview"][data-kind="calc"]');
const linesEditor = (page: Page) => page.locator('[data-testid="widget-editor-calc-input"]');

/** Requests leaving localhost; the offline posture requires none. */
function trackExternal(page: Page): string[] {
  const external: string[] = [];
  page.on('request', (req) => {
    const { hostname } = new URL(req.url());
    if (hostname !== '127.0.0.1' && hostname !== 'localhost') external.push(req.url());
  });
  return external;
}

test.describe('handcalc lines calc preview is inert (no garbage link)', () => {
  test('clicking the read-only lines preview selects the node with no link or navigation', async ({
    page,
  }) => {
    const external = trackExternal(page);
    const consoleErrors: string[] = [];
    page.on('console', (m) => {
      if (m.type() === 'error') consoleErrors.push(m.text());
    });
    let popped = false;
    page.on('popup', () => {
      popped = true;
    });

    await page.goto('/?graph=handcalc_demo');
    await calcPreview(page).waitFor();

    // (d) the equation still typesets via KaTeX (or an honest raw fallback line).
    await expect(
      calcPreview(page).locator('.katex, .ge-calc-preview__line--raw').first(),
    ).toBeVisible();

    // (a) no anchor / href anywhere inside the read-only preview.
    await expect(calcPreview(page).locator('a')).toHaveCount(0);
    await expect(calcPreview(page).locator('[href]')).toHaveCount(0);

    // Click the body of the preview.
    const urlBefore = page.url();
    await calcPreview(page).click({ position: { x: 6, y: 6 } });

    // (c) the click selects the node and opens the inspector (its calc editor
    //     mounts) — the intended read-only behaviour.
    await expect(stepsNode(page)).toHaveClass(/selected/);
    await expect(linesEditor(page)).toBeVisible();

    // (a, cont.) no navigation, no popup window.
    expect(page.url()).toBe(urlBefore);
    expect(popped).toBe(false);

    // (b) no console errors; (e) nothing left localhost.
    expect(consoleErrors).toEqual([]);
    expect(external).toEqual([]);
  });

  test('a calc line carrying raw \\href never renders a clickable link', async ({ page }) => {
    // Drives the exact shared-loader path the card preview uses. An `\href` line
    // is invalid Python, so the server rejects the derive and NOTHING commits —
    // the demo module stays pristine — but the draft still typesets through the
    // same `renderKatex`. With `trust: false` pinned, no `<a>` is produced.
    await page.goto('/?graph=handcalc_demo');
    await calcPreview(page).click({ position: { x: 6, y: 6 } });
    await expect(linesEditor(page)).toBeVisible();

    const original = await linesEditor(page).inputValue();
    const derived = page.waitForResponse(
      (r) => r.url().includes('/derive') && r.request().method() === 'POST',
    );
    await linesEditor(page).fill('margin = \\href{https://evil.example/pwn}{C_min}');
    await derived;

    // The draft preview inside the inspector renders the smuggled \href line but
    // must never turn it into a live anchor.
    const draftPreview = page.locator('[data-testid="calc-preview"]');
    await expect(draftPreview.first()).toBeVisible();
    await expect(draftPreview.locator('a')).toHaveCount(0);
    await expect(draftPreview.locator('[href]')).toHaveCount(0);

    // Restore the original literal so a blur-commit is a no-op (text unchanged),
    // then reload to discard the transient draft — leaves the module untouched.
    await linesEditor(page).fill(original);
    await page.reload();
    await expect(calcPreview(page)).toBeVisible();
  });
});
