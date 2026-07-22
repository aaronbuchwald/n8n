# ADR 0002 — HTTP API (the contract every UI codes against)

Status: accepted (2026-07) · Scope: `graph-engine/server/` · Stream A2

## Context

The web shell, node-library palette, and (later) the source-editing UI all need
the engine over HTTP. This is the shared seam; it must be small and stable so
parallel streams don't diverge.

## Decision

Expose the five engine operations verbatim. The request/response graph payload
**is** the existing graph JSON (`GRAPH_SCHEMA`) — no new graph format, ever.

```
GET  /api/specs                 -> {"version", "specs": {id: node-spec}}     # registry.specs()
POST /api/graphs/validate {graph} -> 200 {"ok": true} | 422 {"ok": false, "errors": [...]}   # bind()
POST /api/run     {graph, environment?} -> {"outputs": {nodeId: {socket: value}}, "order", "output", "errors"}  # run()
POST /api/export  {graph}        -> {"python": "..."}                          # to_python()
GET/PUT /api/source/{spec_id}    -> 501 (reserved for stream E)
```

- **`bind` is the validate endpoint** — the UI calls it on every drag-to-connect.
  Errors are `{code, message, nodeId?}`; `nodeId` is present when the exception
  exposes one (e.g. `NodeExecutionError`).
- **Values** are JSON with a `{"$repr","$type"}` fallback + size cap for
  non-JSON returns (`server/serialize.py`) — the cheap form of ADR 0001's
  "JSON values + opaque handles". Large/opaque values become previews.
- **Synchronous run** in v1. The response shape (`order` + per-node outputs)
  already supports incremental delivery, so SSE/streaming is additive later.
- `environment` on `/api/run` is accepted and ignored until stream C wires the
  sandboxed runner in; in-process run is the dev default.

## Deferred

- Structured per-node bind errors (today the `nodeId` is in the message text for
  bind failures; only runtime `NodeExecutionError` carries it structurally).
- Graph GET/PUT persistence, source editing (stream E), streaming, auth.
