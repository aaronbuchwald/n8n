import { test, expect } from '@playwright/test';

const NODE_TITLES = ['read_values', 'total', 'average', 'render_summary'];

test('renders the graph fetched live from the API (not fixtures)', async ({ page }) => {
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

  // The topbar reflects the contract version returned by /api/specs.
  await expect(page.getByText(/contract v\d+\.\d+\.\d+/)).toBeVisible();

  // The custom nodes mount inside the ReactFlow canvas.
  const canvas = page.getByTestId('flow-canvas');
  await expect(canvas).toBeVisible();

  // All four node titles from the live graph are visible.
  for (const title of NODE_TITLES) {
    await expect(
      page.locator('[data-testid="node-title"]', { hasText: new RegExp(`^${title}$`) }),
    ).toBeVisible();
  }

  // Four nodes total.
  await expect(page.getByTestId('spec-node')).toHaveCount(4);

  // Edges are rendered: the graph has 4 edges, drawn as SVG paths.
  const edgePaths = page.locator('.react-flow__edge-path');
  await expect(edgePaths.first()).toBeVisible();
  expect(await edgePaths.count()).toBe(4);

  // The graph output node is marked.
  await expect(page.getByTestId('output-badge')).toBeVisible();

  // Wait for the fitView animation to SETTLE (viewport transform stops changing)
  // instead of a fixed sleep, which can race on a slow runner.
  const viewport = page.locator('.react-flow__viewport');
  await expect(viewport).toBeVisible();
  await page.waitForFunction(
    () => {
      const el = document.querySelector('.react-flow__viewport') as HTMLElement | null;
      if (!el) return false;
      const t = el.style.transform;
      const w = window as unknown as { __geLastTransform?: string };
      const stable = w.__geLastTransform === t && t.includes('scale');
      w.__geLastTransform = t;
      return stable;
    },
    null,
    { polling: 100, timeout: 5000 },
  );

  // The MiniMap renders one rectangle per node only when node dimensions sync
  // back through onNodesChange. Poll: the minimap re-renders a beat after
  // measurement settles.
  const minimapNodes = page.locator('.react-flow__minimap-node');
  await expect.poll(async () => minimapNodes.count(), { timeout: 10_000 }).toBe(4);
  await expect(minimapNodes.first()).toBeVisible();

  await page.screenshot({ path: 'tests/__screenshots__/graph.png', fullPage: false });

  // Nodes are draggable: onNodesChange must apply position changes.
  const nodeEl = page.locator('.react-flow__node', { hasText: 'total' }).first();
  const box = await nodeEl.boundingBox();
  if (!box) throw new Error('node has no bounding box');
  const before = await nodeEl.evaluate((el) => (el as HTMLElement).style.transform);
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 90, box.y + box.height / 2 + 60, { steps: 8 });
  await page.mouse.up();
  await expect
    .poll(async () => nodeEl.evaluate((el) => (el as HTMLElement).style.transform))
    .not.toBe(before);
});

test('runs the graph and exports it to Python from the UI', async ({ page }) => {
  // The graph must load before Run/Export are enabled.
  await page.goto('/');
  await expect(page.getByTestId('flow-canvas')).toBeVisible();

  const runButton = page.getByTestId('run-button');
  const exportButton = page.getByTestId('export-button');
  await expect(runButton).toBeEnabled();

  // --- Run: POST /api/run, then the output socket value renders in the iframe.
  const runResponse = page.waitForResponse(
    (r) => r.url().includes('/api/run') && r.status() === 200,
  );
  await runButton.click();
  await runResponse;

  // The declared output socket (render_summary.result) is an HTML card shown in
  // the sandboxed iframe. Assert the computed numbers appear INSIDE the frame.
  const frame = page.frameLocator('[data-testid="run-result-frame"]');
  await expect(frame.getByText('Readings summary')).toBeVisible();
  await expect(frame.getByText('25', { exact: true })).toBeVisible();

  // The iframe is fully sandboxed (no scripts / same-origin), never innerHTML.
  await expect(page.getByTestId('run-result-frame')).toHaveAttribute('sandbox', '');

  // Per-node outputs are surfaced (the average node produced 25).
  const results = page.getByTestId('run-results');
  await expect(results).toContainText('average');
  await expect(results).toContainText('total');

  // --- Export: POST /api/export, then the read-only Python panel shows.
  const exportResponse = page.waitForResponse(
    (r) => r.url().includes('/api/export') && r.status() === 200,
  );
  await exportButton.click();
  await exportResponse;

  const code = page.getByTestId('export-code');
  await expect(code).toBeVisible();
  await expect(code).toContainText('from minimal import');
  await expect(code).toContainText('render_summary(');

  // Both the graph and the exported Python are visible side-by-side.
  await expect(page.getByTestId('flow-canvas')).toBeVisible();
  await expect(page.getByTestId('export-panel')).toBeVisible();

  await page.screenshot({ path: 'tests/__screenshots__/run.png', fullPage: false });
});

test('shows an error state when the API fails', async ({ page }) => {
  // Force a server error on the specs endpoint before the app loads.
  await page.route('**/api/specs', (route) =>
    route.fulfill({ status: 500, contentType: 'application/json', body: '{"message":"boom"}' }),
  );

  await page.goto('/');

  // A clear error message, not a blank screen or crashed canvas.
  const error = page.getByTestId('app-error');
  await expect(error).toBeVisible();
  await expect(error).toContainText(/load the graph/i);
  await expect(page.getByTestId('flow-canvas')).toHaveCount(0);
});
