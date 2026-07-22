# graph-engine · web shell (B1)

A read-only [ReactFlow](https://reactflow.dev) view of the graph-engine example
graph. It renders the frozen engine snapshots
(`example.graph.json` + `example.node-specs.json`) as nodes and edges: one node
per graph node showing the spec **title**, its **input sockets** (left handles,
with the bound literal, the `wired` state, or the declared widget) and **output
sockets** (right handles), the docstring as a subtitle/tooltip, and a badge on
the graph's **output** node. Pan / zoom / minimap come from ReactFlow.

This is the Phase 4 "re-render the node graph" checkpoint — **read-only**, no
editing, no server. It reads the same JSON contract the headless engine emits.

## Self-contained / offline

Every asset — React, ReactFlow, its stylesheet, fonts — is installed from npm
and **bundled locally** by Vite. **Nothing is loaded from a CDN** at build or
runtime; `dist/index.html` references only local `./assets/*`.

## Isolation from the n8n monorepo

This app is intentionally **not** a member of the n8n pnpm workspace. It carries
its own `package.json`, its own lockfile, and a one-line `pnpm-workspace.yaml`
that marks `web/` as its own workspace root so pnpm does not walk up into the
surrounding monorepo. Run every command from inside `web/`.

## Install / dev / build / test

```bash
cd graph-engine/web

pnpm install        # install locally (npm registry only)
pnpm dev            # Vite dev server (hot reload) at http://localhost:5173
pnpm build          # typecheck + production bundle into dist/ (offline)
pnpm preview        # serve the built dist/ at http://127.0.0.1:4173
pnpm typecheck      # tsc project references, no emit
pnpm test           # Playwright: builds, serves, asserts nodes + edges, screenshots
```

## The Playwright test

`tests/graph.spec.ts` loads the **built** app via `vite preview`, asserts the
four node titles (`read_values`, `total`, `average`, `render_summary`) are
visible, that four nodes and four edges are drawn, and that the output node is
badged. It saves a screenshot to `tests/__screenshots__/graph.png`.

The environment ships Chromium at `/opt/pw-browsers`; the Playwright config
points `executablePath` at it, so **do not** run `playwright install`.

## Layout

| Path | Role |
|---|---|
| `src/fixtures/` | Copies of the engine's `example.graph.json` + `example.node-specs.json` |
| `src/types.ts` | TypeScript shapes for the engine's JSON contract (v0.2.0) |
| `src/buildGraph.ts` | Fixture JSON → ReactFlow nodes/edges (left-to-right auto-layout, socket handles) |
| `src/components/SpecNode.tsx` | The custom node: title, doc, input/output sockets, output badge |
| `src/App.tsx` | ReactFlow canvas (background, minimap, controls) |
