# graph-engine · web shell (B3 — run + export)

A [ReactFlow](https://reactflow.dev) view of a graph served by the **live**
graph-engine HTTP API. On load the app fetches the palette from `GET /api/specs`
and the graph from `GET /api/graph`, then renders one node per graph node showing
the spec **title**, its **input sockets** (left handles, with the bound literal,
the `wired` state, or the declared widget) and **output sockets** (right handles),
the docstring as a subtitle/tooltip, and a badge on the graph's **output** node.
Pan / zoom / minimap come from ReactFlow.

It renders from the running server — **there are no baked-in fixtures**. If the
server is down or replies non-200, the app shows a clear **error** state; while
the two requests are in flight it shows a **loading** state.

## Run + export (B3)

Two toolbar actions operate on the currently-loaded graph:

- **Run** → `POST /api/run`. The response's per-node socket values are overlaid
  on each node and listed in a **run-results panel** below the canvas. The
  graph's declared output socket (the `render_summary` HTML card) is rendered in
  a **fully sandboxed iframe** (`sandbox=""`, `srcDoc`) — never
  `dangerouslySetInnerHTML` — so untrusted node HTML can't touch the host page.
  JSON-safe values render as-is; non-JSON returns arrive as `{"$repr","$type"}`
  previews (see `server/serialize.py`) and are shown readably. A run error
  (`errors: [{code, message, nodeId?}]`) marks the offending node and is surfaced
  in the panel rather than crashing the app.
- **Export Python** → `POST /api/export`. The returned flat script is shown in a
  read-only, whitespace-preserving code panel **side-by-side with the graph**, so
  the graph ↔ Python correspondence is visible at a glance.

Both buttons show a pending/disabled state while their request is in flight; a
transport failure (server unreachable) clears stale results and shows a banner.

## Where the data comes from

```
browser ──/api/specs──▶  FastAPI server ──▶ registry.specs()   (the palette + contract version)
        └─/api/graph──▶                  └▶ sample graph JSON   (what to render)
```

Run the server with the bundled demo loaded (the *minimal* example — its
`@node`s and traced graph):

```bash
cd graph-engine
uv run --extra server python -m server --demo      # serves specs + sample graph on :8000
```

## Same-origin `/api` (dev, preview, and prod)

The browser calls **relative** `/api/*` paths, so the web and the API must share
an origin. Locally that is done with a **Vite proxy** (`vite.config.ts`), applied
to both `pnpm dev` and `vite preview`: `/api/*` is forwarded to
`GE_API_TARGET` (default `http://127.0.0.1:8000`). This is the simplest path and
is exactly what the Playwright e2e uses.

```bash
GE_API_TARGET=http://127.0.0.1:8000 pnpm dev     # override the target if needed
```

In a real deployment, serve the built `dist/` and the API behind the **same
origin** (a reverse proxy, or FastAPI `StaticFiles` mounting `dist/`); no code
change is needed because the fetches are already same-origin `/api/*`.

## Self-contained / offline

Every asset — React, ReactFlow, its stylesheet, fonts — is installed from npm
and **bundled locally** by Vite. **Nothing is loaded from a CDN** at build or
runtime; `dist/index.html` references only local `./assets/*`. Only the runtime
graph data crosses the wire, from your own `/api`.

## Isolation from the n8n monorepo

This app is intentionally **not** a member of the n8n pnpm workspace. It carries
its own `package.json`, its own lockfile, and a one-line `pnpm-workspace.yaml`
that marks `web/` as its own workspace root so pnpm does not walk up into the
surrounding monorepo. Run every command from inside `web/`.

## Install / dev / build / test

```bash
cd graph-engine/web

pnpm install        # install locally (npm registry only)
pnpm dev            # Vite dev server (hot reload) — proxies /api to the server
pnpm build          # typecheck + production bundle into dist/ (offline)
pnpm preview        # serve the built dist/ at http://127.0.0.1:4173 (proxies /api)
pnpm typecheck      # tsc project references, no emit
pnpm test           # Playwright: boots the server + web, asserts live render + error state
```

## The Playwright test

`tests/graph.spec.ts` boots **both** servers via Playwright `webServer`:

1. the FastAPI server with the demo (`python -m server --demo`) on `:8000`, and
2. the built app via `vite preview` on `:4173`, whose `/api` proxy forwards to it.

It then asserts that `GET /api/specs` and `GET /api/graph` both return 200, that
the four node titles (`read_values`, `total`, `average`, `render_summary`) render
with four nodes / four edges and a badged output node **from the live API**, and
that forcing `/api/specs` to 500 surfaces the error state instead of a blank
canvas. A second test clicks **Run** (asserting the computed `25` appears inside
the sandboxed output iframe) then **Export** (asserting the Python panel shows
`from minimal import` / `render_summary(`). Screenshots are saved to
`tests/__screenshots__/graph.png` (render) and `run.png` (run + export).

The environment ships Chromium at `/opt/pw-browsers`; the Playwright config
points `executablePath` at it, so **do not** run `playwright install`.

## Layout

| Path | Role |
|---|---|
| `src/api.ts` | Fetches `/api/specs` + `/api/graph`; posts `/api/run` + `/api/export`; typed surfaces |
| `src/types.ts` | TypeScript shapes for the engine's JSON contract (v0.2.0) |
| `src/preview.ts` | Renders a socket value (incl. `{"$repr","$type"}` previews) readably |
| `src/buildGraph.ts` | Graph + spec JSON → ReactFlow nodes/edges (auto-layout, socket handles) |
| `src/components/SpecNode.tsx` | The custom node: title, doc, sockets, output badge, per-node run result |
| `src/components/RunResultsPanel.tsx` | Run outputs: sandboxed output iframe + per-node values + errors |
| `src/components/ExportPanel.tsx` | Read-only exported-Python panel beside the canvas |
| `src/GraphView.tsx` | The ReactFlow canvas (background, minimap, controls); folds in run results |
| `src/App.tsx` | Data loading + loading/error/ready states + topbar + Run/Export actions |
