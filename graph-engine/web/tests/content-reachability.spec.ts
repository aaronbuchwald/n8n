import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

import { test, expect, type Page } from '@playwright/test';

import { expectContentReachable } from './reachability';

// ─────────────────────────────────────────────────────────────────────────────
// CONTENT REACHABILITY — the invariant, driven over real app states.
//
// `toBeVisible()` is true for content a container has clipped away forever, so
// the rest of the suite cannot see this bug family. The rule (and its one
// exemption) lives in `reachability.ts`; this spec is only the state matrix:
// every state × viewport where a box could get small enough to clip.
//
// Read-only by construction — it boots, looks, and asserts. Nothing here writes
// to the demo workspace, so it belongs in the parallel `chromium` project.
// ─────────────────────────────────────────────────────────────────────────────

/** Narrow enough that panels really are cramped; wide enough for the normal case. */
const VIEWPORTS = [
  { name: 'narrow-900', width: 900, height: 700 },
  { name: 'wide-1500', width: 1500, height: 900 },
] as const;

/** The showcase graph, and the tall self-sizing calc card (bug #1's repro). */
const SHOWCASE = '/';
const CAPACITY = '/?graph=capacity_check';

async function boot(page: Page, url: string): Promise<void> {
  await page.goto(url);
  await expect(page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]')).toBeVisible({
    timeout: 20_000,
  });
}

async function run(page: Page): Promise<void> {
  const response = page.waitForResponse(
    (r) => new URL(r.url()).pathname.endsWith('/run') && r.status() === 200,
  );
  await page.getByTestId('run-button').click();
  await response;
  await expect(page.getByTestId('run-results')).toBeVisible({ timeout: 20_000 });
}

for (const viewport of VIEWPORTS) {
  test.describe(`content reachability @ ${viewport.name} (${viewport.width}×${viewport.height})`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } });

    test('boot: canvas with nodes rendered', async ({ page }) => {
      await boot(page, SHOWCASE);
      await expect(page.getByTestId('spec-node').first()).toBeVisible();
      await expectContentReachable(page, `boot showcase @ ${viewport.name}`);
    });

    test('after a run: the output panel holds a tall card', async ({ page }) => {
      // Bug #1 lived exactly here: `.ge-results__render { overflow: hidden }`
      // cut a self-sized card off mid-way with no way to scroll to the rest.
      await boot(page, CAPACITY);
      await run(page);
      await expect(page.getByTestId('run-results').getByTestId('html-card-frame')).toBeVisible();
      await expectContentReachable(page, `capacity_check after run @ ${viewport.name}`);
    });

    test('after a run: showcase results, per-node list and render side by side', async ({ page }) => {
      await boot(page, SHOWCASE);
      await run(page);
      await expectContentReachable(page, `showcase after run @ ${viewport.name}`);
    });

    test('node inspector open on a node with long values', async ({ page }) => {
      await boot(page, SHOWCASE);
      await run(page); // run first, so the inspector shows real (long) values
      await page.locator('.react-flow__node[data-id="expr"] .ge-node__header').click();
      await expect(page.getByTestId('node-inspector')).toBeVisible();
      await expectContentReachable(page, `inspector on expr, after run @ ${viewport.name}`);
    });

    test('node catalog popover open', async ({ page }) => {
      await boot(page, SHOWCASE);
      await page.getByTestId('add-node-button').click();
      await expect(page.getByTestId('node-catalog')).toBeVisible();
      await expectContentReachable(page, `node catalog open @ ${viewport.name}`);
    });

    test('collapsed dock rails', async ({ page }) => {
      await boot(page, SHOWCASE);
      await run(page);
      await page.getByTestId('collapse-right').click();
      await expect(page.getByTestId('rail-right')).toBeVisible();
      await page.getByTestId('collapse-bottom').click();
      await expect(page.getByTestId('rail-bottom')).toBeVisible();
      await expectContentReachable(page, `both docks collapsed to rails @ ${viewport.name}`);
    });
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// The calc card, rendered DIRECTLY.
//
// On the canvas that card lives inside `sandbox=""` — an opaque origin
// Playwright cannot evaluate into, and weakening the sandbox to look inside is
// not on the table. So the card HTML is generated here (by importing the real
// calcsheet module — no hand-generated file) and mounted with `setContent`, and
// the SAME invariant runs over it at the widths a node card actually gives it.
//
// This is bug #2's repro: `.card { overflow:hidden }` plus `white-space:nowrap`
// cells meant that at ~280px the rows/checks were wider than the box and
// horizontally unreachable — a vertical scrollbar existed, a horizontal one
// did not.
//
// TWO FIXTURES, and the second one is the lesson. The shipped example's title
// is "Capacity check" — two short words — so for a long time this spec passed
// over a card whose HEAD was clipped at 320px (278px of head in a 262px box,
// cut off by the same `.card { overflow:hidden }`) simply because no fixture
// here had a real sheet heading in it. A convenient fixture is how an invariant
// goes blind, so the long title is now part of the matrix.
// ─────────────────────────────────────────────────────────────────────────────

const CALCSHEET_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../../calcsheet',
);

/** Run a snippet against the real calcsheet module and take its stdout. */
function renderCalcCard(snippet: string): string {
  return execFileSync(
    'uv',
    ['run', '--directory', CALCSHEET_DIR, 'python', '-c', snippet],
    { encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 },
  );
}

/**
 * The shipped example, and the same calc under a heading the length of a real
 * one. Both come from the module — the long title is the pinned example with
 * its title replaced, so it cannot drift away from what calcsheet actually
 * renders, and no HTML is hand-written here.
 */
const LONG_TITLE = 'Support pressure without reinforcement at the intermediate bearing';
const CARDS = [
  {
    name: 'capacity',
    title: 'Capacity check',
    snippet:
      'from calcsheet.examples.capacity import render; import sys; sys.stdout.write(render())',
  },
  {
    name: 'long-titled',
    title: LONG_TITLE,
    snippet:
      'import sys; from dataclasses import replace; from calcsheet import render_html; ' +
      'from calcsheet.examples.capacity import build_calc; ' +
      `sys.stdout.write(render_html(replace(build_calc(), title=${JSON.stringify(LONG_TITLE)}).evaluate()))`,
  },
] as const;

for (const card of CARDS) {
  test.describe(`content reachability — ${card.name} calc card (sandboxed on canvas, rendered directly here)`, () => {
    let cardHtml = '';

    test.beforeAll(() => {
      cardHtml = renderCalcCard(card.snippet);
      expect(cardHtml, 'the calcsheet module must render the card').toContain(card.title);
    });

    // 320 is roughly the node-card width the canvas gives the card; 480 is a
    // cramped dock; 900 is the comfortable case that must not regress either.
    for (const width of [320, 480, 900]) {
      test(`the card keeps every row and check reachable at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 700 });
        await page.setContent(cardHtml);
        await expect(page.locator('.card__title')).toHaveText(card.title);
        // The head and both sections really are present — reachability is only
        // interesting for content that exists.
        await expect(page.locator('.card__head')).toBeAttached();
        await expect(page.locator('.rows').first()).toBeAttached();
        await expect(page.locator('.chk').first()).toBeAttached();
        await expectContentReachable(page, `calcsheet ${card.name} card @ ${width}px wide`);
      });
    }
  });
}
