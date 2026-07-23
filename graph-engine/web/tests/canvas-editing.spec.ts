import { test, expect, type Page } from '@playwright/test';
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

// ADR 0011 stream 11-W4 — canvas structural editing against the LIVE demo
// server (no mocks). The capstone claims, each proven end-to-end:
//  * drag-to-reposition persists to the `<module>.layout.json` sidecar and
//    NEVER produces a `.py` diff (the module file is read before/after — HD3 /
//    the ADR 0008 position-save note), and the position survives a reload;
//  * a palette entry dragged onto the canvas lands AT the drop point, born
//    pinned, and badges "needs wiring" on the canvas node itself;
//  * connecting two nodes persists the edge through the store's source queue
//    (PUT rewrites the real module) and the edge survives a reload;
//  * deleting a node splices it (and its cascaded edges) out of the module;
//  * "Tidy layout" re-lays-out everything and persists every position.
//  * everything serves from localhost — EXTERNAL_REQUESTS must stay 0.
//
// Every test restores the pristine module/sidecar in a finally; the file runs
// serially (its own project, after `palette`) because each test mutates the
// one demo workspace.

const HERE = path.dirname(fileURLToPath(import.meta.url));
const MODULE_PY = path.resolve(HERE, '..', '..', 'examples', 'showcase', 'showcase.py');
const SIDECAR = path.resolve(HERE, '..', '..', 'examples', 'showcase', 'showcase.layout.json');
const PALETTE_SPEC_MIME = 'application/x-graph-engine-spec';

test.describe.configure({ mode: 'serial' });

/** Collect requests leaving localhost; the offline posture requires none. */
function trackExternalRequests(page: Page): string[] {
  const external: string[] = [];
  page.on('request', (req) => {
    const { hostname } = new URL(req.url());
    if (hostname !== '127.0.0.1' && hostname !== 'localhost') external.push(req.url());
  });
  return external;
}

async function openApp(page: Page): Promise<void> {
  await page.goto('/');
  await expect(page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]')).toBeVisible({
    timeout: 15_000,
  });
}

function flowNode(page: Page, id: string) {
  return page.locator(`.react-flow__node[data-id="${id}"]`);
}

const waitForGraphPut = (page: Page) =>
  page.waitForResponse(
    (r) => r.url().endsWith('/api/graph') && r.request().method() === 'PUT' && r.status() === 200,
  );

/** Restore the pristine served graph (positions null → sidecar unlinked). */
async function restore(page: Page, original: unknown): Promise<void> {
  const res = await page.request.put('/api/graph', { data: { graph: original } });
  expect(res.ok()).toBe(true);
}

test('dragging a node persists sidecar-only — zero .py diff — and survives reload', async ({
  page,
}) => {
  const external = trackExternalRequests(page);
  await openApp(page);
  const original = await (await page.request.get('/api/graph')).json();
  const moduleBefore = readFileSync(MODULE_PY, 'utf8');

  try {
    // Drag the `pick` node by its header, well away from where it sits.
    const header = flowNode(page, 'first').locator('.ge-node__header');
    const box = await header.boundingBox();
    expect(box).not.toBeNull();
    if (!box) return;
    const put = waitForGraphPut(page); // the DEBOUNCED position-only save
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + 120, box.y + box.height / 2 + 90, { steps: 8 });
    await page.mouse.up();
    await put;

    // The sidecar now pins the dragged node…
    expect(existsSync(SIDECAR)).toBe(true);
    const sidecar = JSON.parse(readFileSync(SIDECAR, 'utf8')) as Record<
      string,
      { x: number; y: number }
    >;
    expect(sidecar.first).toBeDefined();

    // …and the Python module is BYTE-IDENTICAL: a drag never dirties the .py.
    expect(readFileSync(MODULE_PY, 'utf8')).toBe(moduleBefore);

    // The served graph carries the merged sidecar position, and a full reload
    // renders the node at it (buildFlow honours served positions — HD3).
    const served = (await (await page.request.get('/api/graph')).json()) as {
      nodes: Array<{ id: string; position: { x: number; y: number } | null }>;
    };
    const servedFirst = served.nodes.find((n) => n.id === 'first');
    expect(servedFirst?.position).toEqual(sidecar.first);

    await openApp(page);
    const transform = await flowNode(page, 'first').evaluate((el) => el.style.transform);
    const match = /translate\((-?[\d.]+)px, (-?[\d.]+)px\)/.exec(transform);
    expect(match).not.toBeNull();
    if (!match) return;
    expect(Number(match[1])).toBeCloseTo(sidecar.first.x, 0);
    expect(Number(match[2])).toBeCloseTo(sidecar.first.y, 0);
  } finally {
    await restore(page, original);
  }
  expect(existsSync(SIDECAR)).toBe(false); // null positions restore → sidecar unlinked
  expect(readFileSync(MODULE_PY, 'utf8')).toBe(moduleBefore);
  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});

test('palette drop lands pinned at the drop point; connect persists; delete splices out', async ({
  page,
}) => {
  const external = trackExternalRequests(page);
  await openApp(page);
  const original = await (await page.request.get('/api/graph')).json();

  let mintedId: string | null = null;
  try {
    // ---- drop a sym.pick from the palette at a chosen empty point ----------
    const canvas = page.getByTestId('flow-canvas');
    const canvasBox = await canvas.boundingBox();
    expect(canvasBox).not.toBeNull();
    if (!canvasBox) return;
    const dropX = Math.round(canvasBox.x + canvasBox.width * 0.46);
    const dropY = Math.round(canvasBox.y + canvasBox.height * 0.86);

    const mint = page.waitForResponse(
      (r) => r.url().includes('/api/graph/mint-id') && r.status() === 200,
    );
    const dropPut = waitForGraphPut(page);
    const dataTransfer = await page.evaluateHandle((mime) => {
      const dt = new DataTransfer();
      dt.setData(mime, 'sym.pick');
      return dt;
    }, PALETTE_SPEC_MIME);
    await canvas.dispatchEvent('drop', { dataTransfer, clientX: dropX, clientY: dropY });

    mintedId = ((await (await mint).json()) as { id: string }).id;
    expect(mintedId).not.toBe('pick'); // HD4: dodges the module's call name

    // Born AT the drop point: the node's top-left sits under the cursor drop
    // (screenToFlowPosition round-trips at the current viewport transform).
    const card = flowNode(page, mintedId);
    await expect(card).toBeVisible();
    const cardBox = await card.boundingBox();
    expect(cardBox).not.toBeNull();
    if (!cardBox) return;
    expect(Math.abs(cardBox.x - dropX)).toBeLessThanOrEqual(2);
    expect(Math.abs(cardBox.y - dropY)).toBeLessThanOrEqual(2);

    // Born pinned: the structural save carries the drop position → sidecar.
    await dropPut;
    const served = (await (await page.request.get('/api/graph')).json()) as {
      nodes: Array<{ id: string; position: { x: number; y: number } | null }>;
    };
    expect(served.nodes.find((n) => n.id === mintedId)?.position).not.toBeNull();

    // The "needs wiring" badge is ON THE CANVAS NODE (11-W4 mirrors the store's
    // `incomplete` onto the card): sym.pick's `values` input is required.
    await expect(card.getByTestId('node-needs-wiring')).toBeVisible();

    // ---- connect roots.result -> <minted>.values ---------------------------
    const sourceHandle = flowNode(page, 'roots').locator('[data-handleid="out:result"]');
    const targetHandle = card.locator('[data-handleid="in:values"]');
    const sourceBox = await sourceHandle.boundingBox();
    const targetBox = await targetHandle.boundingBox();
    expect(sourceBox).not.toBeNull();
    expect(targetBox).not.toBeNull();
    if (!sourceBox || !targetBox) return;

    const connectPut = waitForGraphPut(page);
    await page.mouse.move(sourceBox.x + sourceBox.width / 2, sourceBox.y + sourceBox.height / 2);
    await page.mouse.down();
    await page.mouse.move(targetBox.x + targetBox.width / 2, targetBox.y + targetBox.height / 2, {
      steps: 12,
    });
    await page.mouse.up();
    await connectPut;

    // Wired state reflects on the card, and the badge clears (values is wired).
    await expect(card.getByTestId('node-needs-wiring')).toBeHidden();

    await page.screenshot({ path: 'tests/__screenshots__/canvas-editing.png', fullPage: false });

    // The edge survives a full reload — re-parsed from the rewritten module.
    await openApp(page);
    const reloaded = (await (await page.request.get('/api/graph')).json()) as {
      edges: Array<{ source: string; sourceOutput: string; target: string; targetInput: string }>;
    };
    expect(reloaded.edges).toContainEqual({
      source: 'roots',
      sourceOutput: 'result',
      target: mintedId,
      targetInput: 'values',
    });
    await expect(
      page.locator(`.react-flow__edge[data-id*="roots.result->${mintedId}.values"]`),
    ).toBeVisible();

    // ---- delete the node: cascade + splice out of the module ---------------
    const deletePut = waitForGraphPut(page);
    await flowNode(page, mintedId).locator('.ge-node__header').click();
    await page.keyboard.press('Delete');
    await deletePut;

    const afterDelete = (await (await page.request.get('/api/graph')).json()) as {
      nodes: Array<{ id: string }>;
      edges: Array<{ target: string }>;
    };
    expect(afterDelete.nodes.some((n) => n.id === mintedId)).toBe(false);
    expect(afterDelete.edges.some((e) => e.target === mintedId)).toBe(false);

    await openApp(page);
    await expect(flowNode(page, mintedId)).toHaveCount(0);
  } finally {
    await restore(page, original);
  }
  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});

test('"Tidy layout" re-lays-out every node and persists the whole arrangement', async ({
  page,
}) => {
  const external = trackExternalRequests(page);
  await openApp(page);
  const original = await (await page.request.get('/api/graph')).json();

  try {
    // Drag one node far off so tidy visibly has something to fix.
    const header = flowNode(page, 'first').locator('.ge-node__header');
    const box = await header.boundingBox();
    expect(box).not.toBeNull();
    if (!box) return;
    const dragPut = waitForGraphPut(page);
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + 40, box.y + box.height / 2 + 140, { steps: 6 });
    await page.mouse.up();
    await dragPut;
    const dragged = JSON.parse(readFileSync(SIDECAR, 'utf8')) as Record<
      string,
      { x: number; y: number }
    >;

    const tidyPut = waitForGraphPut(page);
    await page.getByTestId('tidy-layout').click();
    await tidyPut;

    // Every node's position is persisted (a tidy you can lose isn't tidy)…
    const sidecar = JSON.parse(readFileSync(SIDECAR, 'utf8')) as Record<
      string,
      { x: number; y: number }
    >;
    const served = (await (await page.request.get('/api/graph')).json()) as {
      nodes: Array<{ id: string }>;
    };
    for (const node of served.nodes) expect(sidecar[node.id]).toBeDefined();
    // …and the dragged-away node was actually re-arranged by the layout.
    expect(sidecar.first).not.toEqual(dragged.first);
  } finally {
    await restore(page, original);
  }
  expect(existsSync(SIDECAR)).toBe(false);
  expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
});
