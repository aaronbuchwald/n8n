import { expect, type Page } from '@playwright/test';

/**
 * Helpers that make the committed `tests/__screenshots__/*.png` captures
 * byte-reproducible across runs and across checkouts.
 *
 * Six distinct sources of churn were measured on an unmodified tree (see the
 * notes on each helper):
 *
 *  1. the real git branch name is painted into the top bar, and its *length*
 *     reflows the whole bar → `stubWorkspace`;
 *  2. CSS transitions still in flight at capture time (the canvas' 0.3s
 *     opacity fade-in, the Run button's 0.15s background) → `animations`;
 *  3. KaTeX's JS/CSS/webfonts are lazily imported, so math-bearing content
 *     reflows at an unpredictable moment → `waitForVisualSettle`;
 *  4. late-arriving panel content shifting layout after the assertions that
 *     the spec waits on have already passed → `waitForVisualSettle`;
 *  5. the canvas' one-shot initial fit racing that same content → `refit`;
 *  6. Chromium's rasterizer itself → the launch flags in playwright.config.ts.
 *
 * A run-varying identifier written into a capture is fixed at its source
 * instead — see FN_NAME in new-node-authoring.spec.ts.
 */

/** Branch label baked into captures instead of whatever branch is checked out. */
export const STUB_BRANCH = 'e2e/fixed-branch';

/** Identical geometry samples required before the page counts as settled. */
const SETTLE_SAMPLES = 3;
const SETTLE_INTERVAL_MS = 200;

/**
 * Pin `GET /api/workspace` to a fixed branch name.
 *
 * The top bar renders the checkout's real git branch (BranchBadge), so an
 * identical app state produced a different PNG in every worktree — and the
 * badge's *width* reflows the whole bar (the action buttons wrap to a second
 * line past a certain length), which shifted the entire page and dirtied
 * 27-77% of every capture.
 *
 * Fulfilled from a static body rather than by rewriting the real response:
 * forwarding it needs `route.fetch()`, whose in-flight round-trip throws
 * "route.fetch: Test ended" when a spec finishes while the badge request is
 * still open. Nothing visual depends on the other fields — `modules` only
 * feeds the badge's `title` tooltip, which no capture renders.
 *
 * Must be installed before `page.goto`.
 */
export async function stubWorkspace(page: Page): Promise<void> {
  await page.route('**/api/workspace', (route) =>
    route.fulfill({
      json: { branch: STUB_BRANCH, detached: false, commit: null, modules: [] },
    }),
  );
}

/**
 * Resolve once the page has stopped moving.
 *
 * A settled condition, never a fixed sleep: the lazily-imported KaTeX chunk,
 * its stylesheet and its webfonts all land after the assertions a spec waits
 * on, and each one reflows the math-bearing cards when it does.
 *
 * The fingerprint below covers every element's box *plus* the counts of
 * loaded resources, registered font faces and stylesheets — so a lazy chunk,
 * a late `@font-face` registration or an injected stylesheet all count as
 * "still moving" and re-arm the streak. That is deliberately not
 * `waitForLoadState('networkidle')`: Playwright discourages it, and here it
 * simply never resolved (it timed out the 60s test budget from inside this
 * helper). The app does no polling, so these counters do converge.
 */
export async function waitForVisualSettle(page: Page): Promise<void> {
  // Resolves once the fonts demanded so far have finished loading.
  await page.evaluate(async () => {
    await document.fonts.ready;
  });

  await page.waitForFunction(
    (samplesRequired: number) => {
      const w = window as unknown as { __geSettle?: { sig: number; count: number } };

      if (document.fonts.status !== 'loaded') {
        w.__geSettle = undefined;
        return false;
      }

      // FNV-1a over every element's rounded box, so any reflow anywhere counts.
      // Mixes integers rather than formatted strings: this walks a page with
      // thousands of elements, and the string version was costly enough to
      // perturb the timing of tests running in the sibling worker.
      let hash = 2166136261;
      const mix = (n: number) => {
        hash ^= n | 0;
        hash = Math.imul(hash, 16777619);
      };
      const elements = document.querySelectorAll('*');
      for (let i = 0; i < elements.length; i++) {
        const r = elements[i].getBoundingClientRect();
        mix(i);
        mix(Math.round(r.x));
        mix(Math.round(r.y));
        mix(Math.round(r.width));
        mix(Math.round(r.height));
      }
      mix(document.fonts.size);
      mix(document.styleSheets.length);
      mix(performance.getEntriesByType('resource').length);
      const sig = hash >>> 0;

      const prev = w.__geSettle;
      w.__geSettle =
        prev && prev.sig === sig ? { sig, count: prev.count + 1 } : { sig, count: 1 };
      return w.__geSettle.count >= samplesRequired;
    },
    SETTLE_SAMPLES,
    // Sampled on an interval rather than every animation frame: the scan above
    // touches every element, and at rAF cadence it burned enough CPU to shift
    // the timing of a mouse-drag test running in the sibling worker. Three
    // stable samples at this interval is also a stronger stillness signal than
    // three consecutive frames.
    { polling: SETTLE_INTERVAL_MS, timeout: 20_000 },
  );
}

/**
 * Capture one of the committed baselines deterministically.
 *
 * `animations: 'disabled'` is the load-bearing option: Playwright
 * fast-forwards finite CSS transitions to their end state, which pins the
 * canvas' `opacity 0 → 1` fade (the probe caught it at opacity 0.0 and 0.038
 * on different runs — a uniform ±7/255 wash over 62% of the frame) and the Run
 * button's background transition. `caret: 'hide'` keeps a blinking text caret
 * out of specs that leave an editor focused.
 */
export async function stableScreenshot(
  page: Page,
  path: string,
  options: { fullPage?: boolean; refit?: boolean } = {},
): Promise<void> {
  // The badge is fetched asynchronously and renders nothing until it resolves,
  // so without this the capture races its arrival (and the bar's height).
  await expect(page.getByTestId('branch-badge')).toBeVisible();
  await waitForVisualSettle(page);

  if (options.refit) {
    // GraphView frames the canvas exactly once (measuring → framing → fitView,
    // GraphView.tsx), using the node sizes ReactFlow has measured by then. On a
    // graph whose cards carry KaTeX math, those heights are still settling, so
    // the one-shot fit lands on stale geometry and the viewport transform came
    // out differently between runs (translate y 158.9 vs 164.6 → the whole
    // canvas shifted). Re-fitting through the canvas' own "fit view" control —
    // same FIT_VIEW options the app uses, no reach into internals — recomputes
    // the frame from settled geometry, so the capture stops depending on when
    // the math finished rendering.
    await page.locator('.react-flow__controls-fitview').click();
    await waitForVisualSettle(page);
  }
  await page.screenshot({
    path,
    fullPage: options.fullPage ?? false,
    animations: 'disabled',
    caret: 'hide',
  });
}
