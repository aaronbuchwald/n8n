# Plan — graph-based Python calculation IDE

A graph IDE where **ordinary Python functions become nodes**, you wire them into
a graph, run it, and it round-trips back to a flat Python script. Phase 0 (the
headless engine) is done; the rest adds a web UI, an execution environment, and
rich node UIs over the same engine.

**Demo scope rule:** all example graphs use **simple mock calculations only**
(sum, average, median, min/max, basic arithmetic, a small symbolic example).
Domain complexity lives *inside* individual nodes and is never needed to
demonstrate the platform. No engineering/structural domain content.

## Phases

- **Phase 0 — headless engine** ✅ `node_spec`, `Graph`, `bind`, `run`,
  `to_python`, decorator/tracing authoring, qualified ids, JSON contract v0.2.0.
- **Phase 4 — web shell** (ReactFlow over a FastAPI service).
- **Phase 5 — rich node UIs** (data grid, equation editor; node-declared widgets).
- **Phase 6 — version control in the UI** (Git + graph-aware diff).

## Workstreams (5 parallel streams)

| Stream | Scope |
|---|---|
| **A · Platform** | packaging ✅, FastAPI server (`specs`/`validate`/`run`/`export`), node-library loader, `pick` node |
| **B · Web shell** | ReactFlow app: render → live specs → run+export → palette/connect/save |
| **C · Execution env** | env descriptor (deps + mounts, default-deny), subprocess + ephemeral `uv` venv runner, mount guard |
| **D · Node packs** | simple-math calc pack (→ HTML via a rendering node), CSV source, mock-API source (in-process, returns same shape as the CSV) |
| **E · Editing + rich UI** | edit a node's function in the UI → write back to its `.py` (imports read-only), equation editor + node-declared widgets |

**Contract-first seams** (agree before parallel UI/env work): the HTTP API, the
graph-level `environment` descriptor (additive schema field), and node-declared
UI via the open `widget.kind` vocabulary + a web renderer registry.

**First wave (parallel):** A2 (API), C1 (env schema), D1/D2 (calc + CSV packs),
B1 (ReactFlow render). See `docs/adr/` for recorded decisions and deferrals.

## Environment constraints

- Toolchain: `uv`, Python 3.10+, node 22 / pnpm, Chromium at `/opt/pw-browsers`
  (`PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`, `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`).
- Network: `pypi.org`, `files.pythonhosted.org`, `registry.npmjs.org` reachable.
- **CDNs are blocked** — every web asset (ReactFlow, MathLive, KaTeX/MathJax) is
  **bundled locally via npm**, never loaded from a CDN at runtime.
- No secrets / no LLM keys required.
