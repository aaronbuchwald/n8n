import { test, expect } from '@playwright/test';

const NODE_TITLES = ['read_values', 'total', 'average', 'render_summary'];

test('renders the example graph read-only in ReactFlow', async ({ page }) => {
  await page.goto('/');

  // The custom nodes mount inside the ReactFlow canvas.
  const canvas = page.getByTestId('flow-canvas');
  await expect(canvas).toBeVisible();

  // All four node titles from the example graph are visible.
  for (const title of NODE_TITLES) {
    await expect(
      page.locator('[data-testid="node-title"]', { hasText: new RegExp(`^${title}$`) }),
    ).toBeVisible();
  }

  // Four nodes total.
  await expect(page.getByTestId('spec-node')).toHaveCount(4);

  // Edges are rendered: the example graph has 4 edges, drawn as SVG paths.
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
  await page.screenshot({ path: 'tests/__screenshots__/graph.png', fullPage: false });
});
