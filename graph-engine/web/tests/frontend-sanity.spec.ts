import { test, expect, type Locator, type Page } from '@playwright/test';

import {
  PANELS,
  actionCount,
  panelCount,
  type Assertion,
  type Interaction,
  type PanelAction,
  type Target,
} from './frontend-registry';

// ─────────────────────────────────────────────────────────────────────────────
// The frontend panel-sanity walk. Imports the canonical registry
// (frontend-registry.ts) and drives EVERY panel and EVERY action against the
// live demo stack, asserting each action's `expect`. One Playwright test per
// panel; each action runs as its own `test.step` from a fresh, layout-ready boot
// so actions never leak state into each other.
//
// Failure signals the walk flags (per the skill):
//   * a failed assertion (the `checks`);
//   * any console error / pageerror (unhandled rejection) during the action;
//   * any request leaving 127.0.0.1/localhost (the offline posture).
//
// Destructive/too-stateful actions (marked `review: true` in the registry) are
// NOT auto-driven — they carry `custom` notes and are recorded as needs-review
// annotations rather than mutating the shared demo workspace. Their authored,
// mutate-and-restore contracts live in the sibling *.spec.ts files the notes
// point at.
//
// Video recording for human review is opt-in via SANITY_RECORD (see test.use
// below). Recordings land under Playwright's output dir
// (test-results/<test>/video.webm). Run commands are documented in the skill
// (.agents/skills/frontend-panel-sanity/SKILL.md).

const RECORD = Boolean(process.env.SANITY_RECORD);

test.use({ video: RECORD ? 'on' : 'off' });

// A short console banner so the coverage is visible in the run log / --list.
test.beforeAll(() => {
  // eslint-disable-next-line no-console
  console.log(
    `[frontend-sanity] registry: ${panelCount()} panels, ${actionCount()} actions` +
      (RECORD ? ' — recording ON (SANITY_RECORD)' : ''),
  );
});

/** Localhost hostnames that count as "internal" for the offline posture. */
const LOCAL_HOSTS = new Set(['127.0.0.1', 'localhost']);

interface Probes {
  /** URLs of any request that left localhost. */
  external: string[];
  /** Console errors + uncaught page errors (unhandled rejections included). */
  errors: string[];
}

/** Attach request/console/pageerror probes to a page for a whole test. */
function attachProbes(page: Page): Probes {
  const probes: Probes = { external: [], errors: [] };
  page.on('request', (req) => {
    try {
      const { hostname } = new URL(req.url());
      if (!LOCAL_HOSTS.has(hostname)) probes.external.push(req.url());
    } catch {
      // A non-URL request target is ignored — it cannot be external.
    }
  });
  page.on('console', (msg) => {
    if (msg.type() === 'error') probes.errors.push(`console.error: ${msg.text()}`);
  });
  page.on('pageerror', (err) => {
    probes.errors.push(`pageerror: ${err.message}`);
  });
  return probes;
}

/** Boot the app at `url` and wait for the canvas to reach layout-ready. */
async function boot(page: Page, url: string): Promise<void> {
  await page.goto(url);
  await expect(
    page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]'),
  ).toBeVisible({ timeout: 20_000 });
}

/** Resolve a registry Target to a Playwright Locator. */
function resolve(page: Page, target: Target): Locator {
  const root: Locator = target.within ? page.getByTestId(target.within) : page.locator('body');
  let locator: Locator = target.testid
    ? root.getByTestId(target.testid)
    : target.selector
      ? root.locator(target.selector)
      : root;
  if (target.role) locator = locator.getByRole(asRole(target.role));
  if (target.hasText !== undefined) locator = locator.filter({ hasText: target.hasText });
  if (target.nth !== undefined) locator = locator.nth(target.nth);
  return locator;
}

// The subset of ARIA roles the registry uses. Kept as a narrowing helper so the
// registry can carry a plain string without leaking `any` into getByRole.
type SupportedRole = 'tab' | 'button' | 'option' | 'listbox' | 'menuitem';
const SUPPORTED_ROLES: readonly SupportedRole[] = ['tab', 'button', 'option', 'listbox', 'menuitem'];
function asRole(role: string): SupportedRole {
  if ((SUPPORTED_ROLES as readonly string[]).includes(role)) return role as SupportedRole;
  throw new Error(`frontend-sanity: unsupported role "${role}" in registry Target`);
}

/** Drag a resize handle (sash) by (dx, dy) px along its axis. */
async function dragHandle(page: Page, target: Target, dx: number, dy: number): Promise<void> {
  const handle = resolve(page, target);
  const box = await handle.boundingBox();
  if (!box) throw new Error(`frontend-sanity: no bounding box for sash ${JSON.stringify(target)}`);
  const cx = box.x + box.width / 2;
  const cy = box.y + box.height / 2;
  await page.mouse.move(cx, cy);
  await page.mouse.down();
  await page.mouse.move(cx + dx, cy + dy, { steps: 8 });
  await page.mouse.up();
}

/** Drive one interaction. `custom` interactions are recorded, not executed. */
async function runInteraction(page: Page, step: Interaction, notes: string[]): Promise<void> {
  switch (step.kind) {
    case 'goto':
      await boot(page, step.url);
      return;
    case 'reload':
      await page.reload();
      await expect(
        page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]'),
      ).toBeVisible({ timeout: 20_000 });
      return;
    case 'waitReady':
      await expect(
        page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]'),
      ).toBeVisible({ timeout: 20_000 });
      return;
    case 'click':
      await resolve(page, step.target).click();
      return;
    case 'fill':
      await resolve(page, step.target).fill(step.value);
      return;
    case 'press':
      await resolve(page, step.target).press(step.key);
      return;
    case 'pressKey':
      await page.keyboard.press(step.key);
      return;
    case 'dragHandle':
      await dragHandle(page, step.target, step.dx, step.dy);
      return;
    case 'waitVisible':
      await expect(resolve(page, step.target)).toBeVisible({ timeout: step.timeoutMs ?? 10_000 });
      return;
    case 'custom':
      notes.push(`step(custom): ${step.note}`);
      return;
  }
}

/** Assert one check. `custom`/`externalRequestsZero` handled specially. */
async function runAssertion(
  page: Page,
  check: Assertion,
  probes: Probes,
  notes: string[],
): Promise<void> {
  switch (check.kind) {
    case 'visible':
      await expect(resolve(page, check.target)).toBeVisible({ timeout: check.timeoutMs ?? 10_000 });
      return;
    case 'hidden':
      await expect(resolve(page, check.target)).toBeHidden();
      return;
    case 'count':
      await expect(resolve(page, check.target)).toHaveCount(check.count);
      return;
    case 'countAtLeast': {
      // `toHaveCount` needs an exact value; assert "at least" via the count.
      await expect
        .poll(async () => resolve(page, check.target).count(), { timeout: 10_000 })
        .toBeGreaterThanOrEqual(check.min);
      return;
    }
    case 'containsText':
      await expect(resolve(page, check.target)).toContainText(check.text, {
        timeout: check.timeoutMs ?? 10_000,
      });
      return;
    case 'attr':
      await expect(resolve(page, check.target)).toHaveAttribute(check.name, check.value ?? '');
      return;
    case 'externalRequestsZero':
      expect(probes.external, `external (non-localhost) requests: ${probes.external.join(', ')}`).toHaveLength(0);
      return;
    case 'custom':
      notes.push(`check(custom): ${check.note}`);
      return;
  }
}

/** Whether an action is fully declarative (safe to auto-drive as-is). */
function isAutoDrivable(action: PanelAction): boolean {
  if (action.review) return false;
  const hasCustomStep = action.steps.some((s) => s.kind === 'custom');
  return !hasCustomStep;
}

// ── One test per panel; each action is a test.step. ──────────────────────────
for (const panel of PANELS) {
  test(`panel: ${panel.name} (${panel.id})`, async ({ page }) => {
    const probes = attachProbes(page);
    const reviewNotes: string[] = [];

    for (const action of panel.actions) {
      await test.step(`${action.id} — ${action.description}`, async () => {
        const notes: string[] = [];
        // Reset probe tallies per action so one action's external requests /
        // console errors don't spill into the next action's assertions.
        probes.external.length = 0;
        probes.errors.length = 0;

        // Fresh boot for every action so they are independent.
        await boot(page, action.url ?? '/');

        if (isAutoDrivable(action)) {
          for (const step of action.steps) await runInteraction(page, step, notes);
          for (const check of action.checks) await runAssertion(page, check, probes, notes);
          // An action is only clean if nothing errored in the console/page.
          expect(probes.errors, `console/page errors: ${probes.errors.join(' | ')}`).toHaveLength(0);
        } else {
          // Review action: run any declarative steps/checks we CAN (they are
          // read-only preludes), record the custom notes for a human, and skip
          // the destructive remainder. The authored spec named in the note owns
          // the full mutate-and-restore contract.
          for (const step of action.steps) await runInteraction(page, step, notes);
          for (const check of action.checks) await runAssertion(page, check, probes, notes);
          reviewNotes.push(`[${panel.id}/${action.id}] ${notes.join(' ; ')}`);
          test.info().annotations.push({
            type: 'needs-review',
            description: `${panel.id}/${action.id}: ${notes.join(' ; ')}`,
          });
        }
      });
    }

    if (reviewNotes.length > 0) {
      // eslint-disable-next-line no-console
      console.log(`[frontend-sanity] ${panel.id}: ${reviewNotes.length} action(s) need human review`);
    }
  });
}
