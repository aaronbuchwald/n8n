import { test, expect } from '@playwright/test';

// The served demo is now the widget SHOWCASE (ADR 0005 integration): the table
// chain (read_table → apply_recipe → table_summary) and the symbolic chain
// (parse_expr → solve_for → … → render_math_card) composed by `dashboard`.
const KEY_TITLES = ['read_table', 'apply_recipe', 'table_summary', 'parse_expr', 'dashboard'];
const NODE_COUNT = 12;
const EDGE_COUNT = 12;

test('renders the showcase graph fetched live from the API (not fixtures)', async ({ page }) => {
  // Prove the render is driven by the server: both endpoints must be hit over
  // HTTP and return 200 before the canvas populates.
  const specsResponse = page.waitForResponse(
    (r) => r.url().includes('/api/specs') && r.status() === 200,
  );
  const graphResponse = page.waitForResponse(
    (r) => r.url().includes('/api/graph') && r.status() === 200,
  );

  await page.goto('/');
  await specsResponse;
  await graphResponse;

  await expect(page.getByText(/contract v\d+\.\d+\.\d+/)).toBeVisible();

  const canvas = page.getByTestId('flow-canvas');
  await expect(canvas).toBeVisible();

  // The showcase's key node titles render.
  for (const title of KEY_TITLES) {
    await expect(
      page.locator('[data-testid="node-title"]', { hasText: new RegExp(`^${title}$`) }),
    ).toBeVisible();
  }

  await expect(page.getByTestId('spec-node')).toHaveCount(NODE_COUNT);

  const edgePaths = page.locator('.react-flow__edge-path');
  await expect(edgePaths.first()).toBeVisible();
  expect(await edgePaths.count()).toBe(EDGE_COUNT);

  // The graph output node (dashboard) is marked.
  await expect(page.getByTestId('output-badge')).toBeVisible();

  await expect(page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]')).toBeVisible({
    timeout: 10_000,
  });

  // The canvas is EDITABLE now: the shell mounts the commit provider, so each
  // unwired literal input renders an editor chip (read-only would show a static
  // value span with no button). Several literal inputs → several chips.
  const chips = page.getByTestId('widget-chip');
  await expect.poll(async () => chips.count(), { timeout: 10_000 }).toBeGreaterThan(3);

  const minimapNodes = page.locator('.react-flow__minimap-node');
  await expect.poll(async () => minimapNodes.count(), { timeout: 10_000 }).toBe(NODE_COUNT);
  await expect(minimapNodes.first()).toBeVisible();

  await page.screenshot({ path: 'tests/__screenshots__/graph.png', fullPage: false });

  // Nodes are draggable: onNodesChange must apply position changes.
  const nodeEl = page.locator('.react-flow__node', { hasText: 'parse_expr' }).first();
  const box = await nodeEl.boundingBox();
  if (!box) throw new Error('node has no bounding box');
  const before = await nodeEl.evaluate((el) => (el as HTMLElement).style.transform);
  await page.mouse.move(box.x + box.width / 2, box.y + 20);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 90, box.y + 80, { steps: 8 });
  await page.mouse.up();
  await expect
    .poll(async () => nodeEl.evaluate((el) => (el as HTMLElement).style.transform))
    .not.toBe(before);
});

test('runs the showcase graph and exports it to Python from the UI', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByTestId('flow-canvas')).toBeVisible();

  const runButton = page.getByTestId('run-button');
  const exportButton = page.getByTestId('export-button');
  await expect(runButton).toBeEnabled();

  // --- Run: POST /api/run, then the composed output card renders in the iframe.
  const runResponse = page.waitForResponse(
    (r) => r.url().includes('/api/run') && r.status() === 200,
  );
  await runButton.click();
  await runResponse;

  // The declared output socket (dashboard.result) is an HTML card in the
  // sandboxed iframe, composing BOTH chains. Since ADR 0010 10-K the dashboard
  // node declares the `html-card` kind, so the panel mounts that renderer's
  // frame (same sandbox posture) instead of the old string-iframe special case.
  const panel = page.getByTestId('run-results');
  const frame = panel.frameLocator('[data-testid="html-card-frame"]');
  await expect(frame.getByText('Sales by region')).toBeVisible();
  await expect(frame.getByText('Quadratic roots')).toBeVisible();

  await expect(panel.getByTestId('html-card-frame')).toHaveAttribute('sandbox', '');

  // Per-node outputs are surfaced (nodes appear by their graph id).
  const results = page.getByTestId('run-results');
  await expect(results).toContainText('sales'); // apply_recipe node
  await expect(results).toContainText('table_card'); // table_summary node

  // --- Export: POST /api/export, then the read-only Python panel shows.
  const exportResponse = page.waitForResponse(
    (r) => r.url().includes('/api/export') && r.status() === 200,
  );
  await exportButton.click();
  await exportResponse;

  const code = page.getByTestId('export-code');
  await expect(code).toBeVisible();
  await expect(code).toContainText('read_table(');
  await expect(code).toContainText('dashboard(');

  await expect(page.getByTestId('flow-canvas')).toBeVisible();
  await expect(page.getByTestId('export-panel')).toBeVisible();

  await page.screenshot({ path: 'tests/__screenshots__/run.png', fullPage: false });
});

test('shows an error state when the API fails', async ({ page }) => {
  await page.route('**/api/specs', (route) =>
    route.fulfill({ status: 500, contentType: 'application/json', body: '{"message":"boom"}' }),
  );

  await page.goto('/');

  const error = page.getByTestId('app-error');
  await expect(error).toBeVisible();
  await expect(error).toContainText(/load the graph/i);
  await expect(page.getByTestId('flow-canvas')).toHaveCount(0);
});
