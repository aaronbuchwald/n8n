# ADR 0008 note — position saves vs source-mutating saves (two consistency classes)

Status: **decided** (2026-07-23, stream 8-S1) · Companion to ADR 0008 (frontend
sync model) · Pins **0011-D3 / HD3** (eager-vs-batched position saves) so the
canvas-editing stream **11-W4** can code against it. · Read together with
`graph-engine/web/src/store/queue.ts`.

## Context

ADR 0008's single-flight write queue (`store/queue.ts`) exists to keep
**source-mutating** writes consistent: a widget literal commit, and (11-W4) a
wiring change, both rewrite the `.py` (`PUT /api/graph` → the server reparses
and re-serves the graph). Those go through the queue: optimistic overlay,
latest-wins coalescing per `(nodeId, param)`, seq-gated ingestion, rollback on
reject. That machinery is correct *because* every such write contends for the
same authoritative resource — the module source.

**Node positions are not that resource.** The server writes positions to a
`<module>.layout.json` **sidecar**, never to the `.py`
(`server/workspace.py::save_graph`: `positions = {…}; layout.write_text(…)`;
`parse_graph` merges the sidecar back). Positions are presentation state; a drag
must never rewrite Python, block a wiring save, or be coalesced against one.

## Decision — two classes, deliberately kept apart

1. **Source-mutating saves** (widget literal commit, wiring connect/delete,
   structural add/remove) → **the single-flight queue** in `store/queue.ts`.
   Authoritative, seq-gated, optimistic-with-rollback. They dirty the `.py`.

2. **Position-only saves** (node drag) → a **separate, sidecar-only, debounced,
   non-conflicting** path. They are:
   - **debounced** (coalesced by node id — the *last* position per node wins),
     because a drag emits a stream of intermediate coordinates no one needs
     persisted;
   - **non-conflicting** — they carry positions **only**, so they never contend
     with a wiring/literal save and must **never** enter the source queue's
     single-flight lock or its `(nodeId, param)` coalescing (a position save
     that waited behind, or merged with, a wiring save would be a latency and
     correctness bug);
   - **sidecar-only** — they **never dirty the `.py`** (they touch
     `*.layout.json` exclusively), so a position save leaves the source
     bijection (ADR 0004) untouched and does **not** bump the run-staleness
     `rev` (dragging a node does not invalidate a run).

This is **HD3 "sidecar-authoritative"** made concrete: layout lives beside the
module, and the two write paths share no lock, no queue, and no epoch.

## Contract for 11-W4 (what the canvas stream may rely on)

- **Do not route drags through `store/queue.ts`.** That queue is for writes that
  change the module. Add a distinct position-save path (its own debounce +
  in-flight guard, keyed by node id) that PUTs positions to the sidecar.
- **A position save must be `rev`-neutral.** It must not call `ingestGraph`
  (which bumps `rev` and would falsely mark the last run stale). If it needs to
  reflect the persisted position in the store, ingest it through a
  position-only action that leaves `rev`, `run`, and `pending` unchanged.
- **A source-mutating save's response is authoritative for wiring, not for
  layout.** `ingestGraph` replaces the graph; positions come from the merged
  sidecar, so an in-flight drag is never clobbered by a concurrent wiring save
  and vice-versa.
- **Ordering is independent.** Because the two paths share no lock, a drag and a
  wiring edit may be in flight simultaneously; neither can revert the other
  (different resources: sidecar vs `.py`).

## Why not one queue for both

Folding positions into the single-flight source queue would make every drag
frame either (a) rewrite the `.py` (violating ADR 0004 — presentation must not
mutate source) or (b) wait behind an unrelated wiring save (needless latency),
and would bump `rev` on every drag (falsely staling runs — Gap G1's inverse).
Two classes cost one extra debounced path and remove all four hazards.
