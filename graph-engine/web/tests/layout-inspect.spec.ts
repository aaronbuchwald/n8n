import { test, expect, type Page } from '@playwright/test';

interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

const overlaps = (a: Box, b: Box) =>
  a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;

// Handles intentionally sit ON the card border, so containment checks use a
// small tolerance for antialiasing/subpixel rounding — not for real overflow.
const TOLERANCE = 1.5;

const within = (inner: Box, outer: Box) =>
  inner.x >= outer.x - TOLERANCE &&
  inner.y >= outer.y - TOLERANCE &&
  inner.x + inner.width <= outer.x + outer.width + TOLERANCE &&
  inner.y + inner.height <= outer.y + outer.height + TOLERANCE;

// The showcase demo (ADR 0005): 12 nodes across two chains.
const NODE_COUNT = 12;

async function gotoAndSettle(page: Page) {
  await page.goto('/');
  await expect(page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]')).toBeVisible({
    timeout: 15_000,
  });
}

test('auto-layout places every node without overlaps, framed in the viewport', async ({
  page,
}) => {
  await gotoAndSettle(page);

  const nodes = page.getByTestId('spec-node');
  await expect(nodes).toHaveCount(NODE_COUNT);

  const boxes: Box[] = [];
  for (let i = 0; i < NODE_COUNT; i++) {
    const box = await nodes.nth(i).boundingBox();
    expect(box, `node ${i} has a bounding box`).not.toBeNull();
    boxes.push(box as Box);
  }

  // Framed: every node fully inside the browser viewport after fitView.
  const viewport = page.viewportSize();
  expect(viewport).not.toBeNull();
  const vp = { x: 0, y: 0, width: viewport?.width ?? 0, height: viewport?.height ?? 0 };
  for (const [i, box] of boxes.entries()) {
    expect(within(box, vp), `node ${i} is inside the viewport`).toBe(true);
  }

  // Non-overlapping, pairwise.
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      expect(overlaps(boxes[i], boxes[j]), `nodes ${i} and ${j} do not overlap`).toBe(false);
    }
  }
});

test('a long literal value stays inside the node card', async ({ page }) => {
  await gotoAndSettle(page);

  // The demo binds an absolute CSV path (long string) to read_table.path.
  const node = page.locator('[data-testid="spec-node"][data-node-title="read_table"]');
  await expect(node).toBeVisible();
  const nodeBox = (await node.boundingBox()) as Box;

  // The path literal is editable now (a chip button), still clipped to the card.
  const value = node.getByTestId('widget-chip').first();
  await expect(value).toBeVisible();
  const valueBox = (await value.boundingBox()) as Box;
  expect(within(valueBox, nodeBox), 'literal value is clipped inside the card').toBe(true);

  // Audit every text-bearing element of every card: nothing renders outside
  // its card's border (handles are excluded — they sit on the border by design).
  const nodesCount = await page.getByTestId('spec-node').count();
  for (let i = 0; i < nodesCount; i++) {
    const card = page.getByTestId('spec-node').nth(i);
    const cardBox = (await card.boundingBox()) as Box;
    const parts = card.locator(
      '.ge-node__title, .ge-node__doc, .ge-socket__name, .ge-socket__type, .ge-socket__state, .ge-node__result-value, .ge-node__result-socket',
    );
    const partCount = await parts.count();
    for (let j = 0; j < partCount; j++) {
      const partBox = await parts.nth(j).boundingBox();
      if (!partBox) continue;
      expect(within(partBox, cardBox), `card ${i} part ${j} stays inside the card`).toBe(true);
    }
  }
});

test('clicking a node reveals its inputs and outputs, live after a run', async ({ page }) => {
  await gotoAndSettle(page);

  // Before any run, inspecting shows the static wiring. `table_card` is the
  // table_summary node: its `table` input is wired from `sales` (apply_recipe),
  // its `title` is a literal.
  await page.locator('.react-flow__node[data-id="table_card"]').click();
  const inspector = page.getByTestId('node-inspector');
  await expect(inspector).toBeVisible();
  await expect(page.getByTestId('inspector-title')).toHaveText('table_summary');
  await expect(inspector.getByTestId('inspector-no-run')).toBeVisible();
  const inputs = inspector.getByTestId('inspector-inputs');
  await expect(inputs).toContainText('table');
  await expect(inputs).toContainText('sales.result'); // wired source
  await expect(inputs).toContainText('Sales by region'); // title literal
  await expect(inspector.getByTestId('inspector-outputs')).toContainText('result');

  // Run the graph; the open inspector picks up the resolved values.
  const runResponse = page.waitForResponse(
    (r) => r.url().includes('/api/run') && r.status() === 200,
  );
  await page.getByTestId('run-button').click();
  await runResponse;

  // The node now has a resolved run value (the no-run note is gone).
  await expect(inspector.getByTestId('inspector-no-run')).toHaveCount(0);

  // Inspecting the literal-bound source node shows the full path value.
  await page.locator('.react-flow__node[data-id="raw"]').click();
  await expect(page.getByTestId('inspector-title')).toHaveText('read_table');
  await expect(page.getByTestId('inspector-inputs')).toContainText('showcase.csv');

  // Clicking the empty pane closes the inspector.
  await page.locator('.react-flow__pane').click({ position: { x: 40, y: 40 } });
  await expect(inspector).toHaveCount(0);
});
