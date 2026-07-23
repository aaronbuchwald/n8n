import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

import { test, expect, type Page } from '@playwright/test';

// ADR 0011 D7/HD1 (stream 11-W6): defining a brand-new @node in Monaco, written
// to a real backing .py, immediately placeable. Runs against the live demo
// (showcase.py) — no spec rewriting, no network beyond localhost
// (EXTERNAL_REQUESTS must stay 0). HD1's property under test: the write
// destination is shown BEFORE the write happens, never a silent default.

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SHOWCASE_FILE = path.join(HERE, '..', '..', 'examples', 'showcase', 'showcase.py');

interface MonacoModel {
  getValue(): string;
  setValue(value: string): void;
}
interface MonacoEditorInstance {
  getValue(): string;
  getModel(): MonacoModel | null;
}
interface MonacoBridge {
  editor: { getEditors(): MonacoEditorInstance[] };
}

async function gotoAndSettle(page: Page) {
  await page.goto('/');
  await expect(page.locator('[data-testid="flow-canvas"][data-layout-ready="true"]')).toBeVisible({
    timeout: 15_000,
  });
}

async function waitForMonaco(page: Page) {
  await expect(page.getByTestId('source-monaco')).toBeVisible();
  await page.waitForFunction(() => {
    const w = window as unknown as { monaco?: MonacoBridge };
    const editors = w.monaco?.editor.getEditors() ?? [];
    return editors.length > 0 && editors[0].getValue().length > 0;
  });
}

async function setMonacoValue(page: Page, value: string) {
  await page.evaluate((next) => {
    const w = window as unknown as { monaco: MonacoBridge };
    w.monaco.editor.getEditors()[0].getModel()?.setValue(next);
  }, value);
}

/** Collect requests leaving localhost; the offline posture requires none. */
function trackExternalRequests(page: Page): string[] {
  const external: string[] = [];
  page.on('request', (req) => {
    const { hostname } = new URL(req.url());
    if (hostname !== '127.0.0.1' && hostname !== 'localhost') external.push(req.url());
  });
  return external;
}

test('authoring a new @node in Monaco shows the destination before writing, then registers it', async ({
  page,
}) => {
  const external = trackExternalRequests(page);
  const originalFile = readFileSync(SHOWCASE_FILE, 'utf-8');
  const fnName = `e2e_new_node_${crypto.randomUUID().replace(/-/g, '').slice(0, 8)}`;

  try {
    await gotoAndSettle(page);

    // No palette yet (11-W5 lands the header trigger later) — the topbar
    // stand-in entry point opens the create-mode editor.
    await page.getByTestId('new-node-button').click();
    const panel = page.getByTestId('new-node-panel');
    await expect(panel).toBeVisible();
    const editor = panel.getByTestId('source-editor');
    await expect(editor).toBeVisible();

    // HD1's key property: the destination is shown BEFORE any write — visible
    // the moment the panel opens, not revealed only after submitting.
    const dest = editor.getByTestId('source-dest');
    await expect(dest).toBeVisible();
    await expect(dest).toContainText('will be written to');
    await expect(dest).toContainText('showcase.py');
    await expect(editor.getByTestId('source-save-button')).toBeEnabled();

    // The "(change)" picker lists the eligible modules — an honest escape
    // hatch, not hidden magic — and showcase.py is offered as the default.
    await editor.getByTestId('source-dest-change').click();
    const picker = editor.getByTestId('source-dest-picker');
    await expect(picker).toBeVisible();
    await expect(picker).toContainText('showcase.py');
    await picker.getByTestId(/^source-dest-option-/).first().click();
    await expect(picker).toHaveCount(0);
    // Selecting the (only) option keeps the destination line showing it.
    await expect(dest).toContainText('showcase.py');

    // Author the function in Monaco (replacing the pre-filled D7 template).
    await waitForMonaco(page);
    expect(await page.evaluate(() => {
      const w = window as unknown as { monaco: MonacoBridge };
      return w.monaco.editor.getEditors()[0].getValue();
    })).toMatch(/def my_node/);

    const newSource = [
      '@node',
      `def ${fnName}(value: float, factor: float = 2.0) -> float:`,
      '    """Scale value by factor (e2e new-node authoring check)."""',
      '    return value * factor',
      '',
    ].join('\n');
    await setMonacoValue(page, newSource);

    const create = page.waitForResponse(
      (r) => r.url().includes('/api/source') && r.request().method() === 'POST',
    );
    await editor.getByTestId('source-save-button').click();
    const createRes = await create;
    expect(createRes.status()).toBe(200);

    await expect(editor.getByTestId('source-notice')).toContainText(`Created ${fnName}`);
    await expect(editor.getByTestId('source-notice')).toContainText('showcase.py');
    await expect(editor.getByTestId('source-error')).toHaveCount(0);

    // It registered: the palette a UI renders from (`GET /api/specs`) serves it.
    const specs = await (await page.request.get('/api/specs')).json();
    expect(Object.keys(specs.specs)).toContain(`showcase.${fnName}`);

    await page.screenshot({ path: 'tests/__screenshots__/new-node-authoring.png', fullPage: false });

    expect(external, 'EXTERNAL_REQUESTS must be 0').toHaveLength(0);
  } finally {
    // Restore the real example file exactly as found, then force a reimport
    // so the shared demo server (and every other parallel test) sees it
    // pristine again — mirrors the restore pattern in source-editing.spec.ts.
    writeFileSync(SHOWCASE_FILE, originalFile, 'utf-8');
    const before = await (await page.request.get('/api/source/showcase.dashboard')).json();
    const restore = await page.request.put('/api/source/showcase.dashboard', {
      data: { source: before.source },
    });
    expect(restore.ok()).toBe(true);
  }
});

test('a rejected create (name collision) surfaces inline and never writes the file', async ({
  page,
}) => {
  const originalFile = readFileSync(SHOWCASE_FILE, 'utf-8');
  try {
    await gotoAndSettle(page);
    await page.getByTestId('new-node-button').click();
    const editor = page.getByTestId('new-node-panel').getByTestId('source-editor');
    await expect(editor.getByTestId('source-dest')).toContainText('will be written to');

    await waitForMonaco(page);
    // "dashboard" already exists in showcase.py — a legal-looking @node that
    // nonetheless collides with an existing top-level name (D7).
    await setMonacoValue(
      page,
      '@node\ndef dashboard(x: int = 0) -> int:\n    return x\n',
    );

    const create = page.waitForResponse(
      (r) => r.url().includes('/api/source') && r.request().method() === 'POST',
    );
    await editor.getByTestId('source-save-button').click();
    expect((await create).status()).toBe(400);

    await expect(editor.getByTestId('source-error')).toContainText('dashboard');
    await expect(editor.getByTestId('source-notice')).toHaveCount(0);
    expect(readFileSync(SHOWCASE_FILE, 'utf-8')).toBe(originalFile);
  } finally {
    writeFileSync(SHOWCASE_FILE, originalFile, 'utf-8');
  }
});
