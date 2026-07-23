---
name: n8n:frontend-panel-sanity
description: Walk every panel and every user action of the graph-engine web UI and sanity-check each for unexpected behavior, with an option to record video for human review. Use when asked to "check the frontend panels", "sanity-check the UI", "walk every panel/action", verify the graph-engine web app end-to-end, or audit the demo UI for regressions.
---

# Frontend panel sanity

Systematically exercise the graph-engine web UI (`graph-engine/web`) — every main
panel and every user action it supports — against the live demo stack, asserting
each action's expected observable result and flagging anything unexpected.

## The canonical enumerable list

The authoritative, typed inventory of panels + actions is:

```
graph-engine/web/tests/frontend-registry.ts
```

It exports `PANELS: Panel[]`. Each `Panel` has an `id`, `name`, human
`description`, the real `testids` it owns, and `actions[]`. Each `PanelAction`
carries a human `trigger` (the concrete gesture — which `data-testid` to
click/fill/press) and `expect` (the observable result — a real testid/class),
plus a machine `steps`/`checks` encoding the harness executes. Helpers
`panelCount()` and `actionCount()` report coverage.

**This registry is the source of truth.** When the UI changes, update it first;
the harness and this skill follow it. Never invent testids — every value in the
registry is read out of `graph-engine/web/src/**` and cross-checked against the
authored `graph-engine/web/tests/*.spec.ts` contracts.

## The harness

```
graph-engine/web/tests/frontend-sanity.spec.ts
```

imports the registry and emits one Playwright test per panel; each action runs as
its own `test.step`, from a fresh layout-ready boot so actions stay independent.
For each action it drives the `steps` and asserts every `check`.

## Procedure

Iterate **every panel and every action** in the registry against the live demo
stack. For each action:

1. Boot the app at the action's `url` (default `/`) and wait for the canvas to
   reach `[data-testid="flow-canvas"][data-layout-ready="true"]`.
2. Drive the action's `trigger` (its `steps`).
3. Assert its `expect` (its `checks`).

Flag an action as **unexpected behavior** on any of:

- a **failed assertion** (a `check` did not hold);
- a **console error** or **pageerror / unhandled rejection** during the action
  (the harness attaches `console`/`pageerror` probes and fails the step if any
  fire);
- a **non-zero external request** — anything leaving `127.0.0.1`/`localhost`
  (the offline posture requires exactly 0; every panel asserts this).

### Destructive actions (`review: true`)

Actions that rewrite the shared demo module (create node, save source, commit a
calc equation, drag/connect/delete on the canvas, tidy layout) or that are too
stateful to encode declaratively are marked `review: true` in the registry and
carry `custom` notes. The harness does **not** auto-drive these against the
shared workspace — it runs any read-only prelude it can, records the action as a
`needs-review` annotation, and points at the authored `*.spec.ts` that owns the
full mutate-and-restore contract (e.g. `palette.spec.ts`, `canvas-editing.spec.ts`,
`calc-widget.spec.ts`, `source-editing.spec.ts`, `new-node-authoring.spec.ts`,
`stale-run-sync.spec.ts`). To sanity-check those flows for real, run the named
spec (it restores the demo to pristine in a `finally`).

## Recording for human review

Video recording is opt-in via the `SANITY_RECORD` env flag. When set, the
harness declares `test.use({ video: 'on' })` and Playwright writes a
`video.webm` per test under the output dir (`test-results/<test-name>/`).
Recordings, plus any `needs-review` annotations, are the artifact a human reviews.

## Commands

Run from `graph-engine/web`. **Do not** run `playwright install` — Chromium is
pre-installed and pinned in `playwright.config.ts`.

```bash
# Enumerate the whole walk (no stack needed) — sanity of the registry itself:
pnpm exec playwright test tests/frontend-sanity.spec.ts --list

# Walk every panel/action against the live demo stack (boots FastAPI + the built
# web bundle via the config's webServer; asserts each expect):
pnpm exec playwright test tests/frontend-sanity.spec.ts --reporter=list 2>&1 | tail -60

# Same walk, RECORDING video of each panel for human review:
SANITY_RECORD=1 pnpm exec playwright test tests/frontend-sanity.spec.ts --reporter=list
#   → recordings land in graph-engine/web/test-results/<test-name>/video.webm

# One panel only (grep the panel name or id):
pnpm exec playwright test tests/frontend-sanity.spec.ts --grep "Workbench shell"
```

Typecheck after editing the registry or harness:

```bash
pnpm -C graph-engine/web typecheck
```

## Notes

- The walk boots the live stack (ports 8000 API / 4173 web via
  `playwright.config.ts` `webServer`). If a concurrent job holds those ports, do
  authoring + `--list` + `typecheck` only and let the orchestrator run the real
  pass.
- Keep the registry and the authored `*.spec.ts` in agreement: the specs are the
  detailed, restore-safe contracts; the registry is the enumerable index over
  them. A new panel/action means: add it to `frontend-registry.ts` (grounded in
  real testids), then re-run `--list` to confirm it enumerates.
