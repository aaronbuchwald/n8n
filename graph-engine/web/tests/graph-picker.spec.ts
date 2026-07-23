import { test, expect, type Page } from '@playwright/test';

// ADR 0009: the demo server discovers every bundled example, so the top-bar
// picker is visible and switches the canvas live between entry points — each
// with its own graph, layout, and run directory, on the same branch.

const SHOWCASE_NODE_COUNT = 12;
const MINIMAL_NODE_COUNT = 4;

/** Record any request that leaves the local test stack (must stay at zero). */
function trackExternalRequests(page: Page): string[] {
  const external: string[] = [];
  page.on('request', (request) => {
    const { hostname, protocol } = new URL(request.url());
    if (protocol === 'data:' || protocol === 'blob:') return;
    if (hostname === '127.0.0.1' || hostname === 'localhost') return;
    external.push(request.url());
  });
  return external;
}

async function expectNodeTitle(page: Page, title: string) {
  await expect(
    page.locator('[data-testid="node-title"]', { hasText: new RegExp(`^${title}$`) }),
  ).toBeVisible();
}

test('lists the bundled entry points and switches the canvas live', async ({ page }) => {
  const external = trackExternalRequests(page);

  await page.goto('/');

  // Default entry: the showcase, exactly as before the picker existed.
  await expect(page.getByTestId('spec-node')).toHaveCount(SHOWCASE_NODE_COUNT);
  await expectNodeTitle(page, 'dashboard');

  // Several entries discovered → the picker is visible and lists them.
  const pickerButton = page.getByTestId('graph-picker-button');
  await expect(pickerButton).toBeVisible();
  await pickerButton.click();
  const menu = page.getByTestId('graph-picker-menu');
  await expect(menu).toBeVisible();
  await expect(page.getByTestId('graph-picker-option-showcase')).toBeVisible();
  await expect(page.getByTestId('graph-picker-option-capacity_check')).toBeVisible();
  await expect(page.getByTestId('graph-picker-option-minimal')).toBeVisible();
  await pickerButton.click(); // close again

  // Populate a per-entry panel so the switch has something to clear.
  await page.getByTestId('run-button').click();
  await expect(page.getByTestId('run-results')).toBeVisible({ timeout: 30_000 });

  // Switch showcase → minimal: URL carries the selection, the canvas swaps
  // entirely, and the run panel (meaningless across entries) is cleared.
  await pickerButton.click();
  await page.getByTestId('graph-picker-option-minimal').click();
  await expect(page).toHaveURL(/\?graph=minimal/);
  await expect(page.getByTestId('spec-node')).toHaveCount(MINIMAL_NODE_COUNT);
  await expectNodeTitle(page, 'read_values');
  await expect(page.getByTestId('run-results')).toBeHidden();
  await expect(
    page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]'),
  ).toBeVisible({ timeout: 10_000 });

  // Switch minimal → capacity_check: a third live view on the same server.
  await pickerButton.click();
  await page.getByTestId('graph-picker-option-capacity_check').click();
  await expect(page).toHaveURL(/\?graph=capacity_check/);
  await expectNodeTitle(page, 'check_capacity');
  await expect(
    page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]'),
  ).toBeVisible({ timeout: 10_000 });

  // The branch badge is checkout-global — same badge for every entry.
  await expect(page.getByTestId('branch-badge')).toBeVisible();

  await page.screenshot({
    path:
      '/tmp/claude-0/-home-user-n8n/bb1be04a-e997-58f7-9016-e77b3574a884/scratchpad/graph-picker-capacity-check.png',
  });

  // Offline guarantee: nothing left the local stack.
  expect(external, `external requests: ${external.join(', ')}`).toHaveLength(0);
});

test('deep link ?graph=minimal opens that entry directly', async ({ page }) => {
  const external = trackExternalRequests(page);

  await page.goto('/?graph=minimal');
  await expect(page.getByTestId('spec-node')).toHaveCount(MINIMAL_NODE_COUNT);
  await expectNodeTitle(page, 'render_summary');

  expect(external, `external requests: ${external.join(', ')}`).toHaveLength(0);
});
