import { test, expect, type Page, type Locator } from '@playwright/test';

// Regression for the "bottom-right nodes are unclickable" bug: the ReactFlow
// minimap overlays the bottom-right of the canvas. It used to be interactive
// (`pannable zoomable`), so it captured pointer events across its whole rect and
// a node beneath it could never be selected. The fix makes the minimap a
// NON-INTERACTIVE overview (`pointer-events: none` in styles.css) so clicks pass
// THROUGH to the node underneath, while the minimap stays visible for orientation.
//
// Two specs previously worked around this (source-editing hid the minimap;
// graph widened the viewport). This spec proves the workaround is no longer
// needed: with the minimap present AND overlapping the target node, the node is
// still selectable.

async function gotoAndSettle(page: Page) {
  await expect(page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]')).toBeVisible({
    timeout: 15_000,
  });
}

/** True when two bounding boxes share any area. */
function overlaps(a: NonNullable<Awaited<ReturnType<Locator['boundingBox']>>>, b: typeof a) {
  return (
    a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y
  );
}

async function boundingBox(locator: Locator) {
  const box = await locator.boundingBox();
  expect(box, 'element must be laid out with a bounding box').not.toBeNull();
  return box!;
}

test('a node beneath the minimap is still clickable, with the minimap present', async ({
  page,
}) => {
  // Append one extra node with no position so auto-layout drops it into the
  // bottom-right corner — directly under the minimap. This is the same corner
  // node source-editing.spec appends as its `ghost`, but here we do NOT hide the
  // minimap: the fix must let the click land regardless.
  const original = await (await page.request.get('/api/graph')).json();
  const withCornerNode = {
    ...original,
    nodes: [
      ...original.nodes,
      { id: 'corner', type: 'nope.missing', inputs: {}, position: null },
    ],
  };
  await page.route('**/api/graph', async (route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(withCornerNode),
      });
    }
    return route.continue();
  });

  await page.setViewportSize({ width: 1600, height: 900 });
  await page.goto('/');
  await gotoAndSettle(page);

  // The minimap is present and visible — the visual overview is intact.
  const minimap = page.locator('.react-flow__minimap');
  await expect(minimap).toBeVisible();

  // The corner node genuinely sits UNDER the minimap; otherwise this test would
  // prove nothing about pass-through.
  const cornerHeader = page.locator('.react-flow__node[data-id="corner"] .ge-node__header');
  const minimapBox = await boundingBox(minimap);
  const headerBox = await boundingBox(cornerHeader);
  expect(
    overlaps(headerBox, minimapBox),
    'the corner node header must overlap the minimap for this regression to be meaningful',
  ).toBe(true);

  // The core assertion: clicking the header — through the minimap — selects the
  // node and opens the inspector. No `display:none` workaround.
  await cornerHeader.click();
  await expect(page.getByTestId('node-inspector')).toBeVisible();

  // The minimap is still there after the click; only its interactivity is gone.
  await expect(minimap).toBeVisible();
});
