# ADR 0003 — the execution-environment descriptor (declarative, deny-all default)

Status: accepted (2026-07) · Scope: `graph-engine/` · Stream C1

Records the graph-level `environment` block: what it declares, why it is
purely declarative, why every default denies, and — explicitly — what it does
**not** yet do. Enforcement is a later PR; this ADR is the seam the enforcement
work (C2–C5) codes against so the schema never has to bump when the backend
changes.

## Context

A graph is ordinary Python that we want to run somewhere other than the
API process. Streams C2–C5 will run each graph in a subprocess against an
ephemeral `uv` venv with a mount guard. Those streams need a place in the saved
graph to answer three questions before any runner exists:

- which third-party packages must be installed (the engine core itself stays
  pure stdlib — see ADR 0001);
- which host files the graph may read/write;
- whether the graph may touch the network.

ADR 0001 already reserved "an `implementation` / runtime-env block … define it
when an executor **service** exists" and kept the schema additive-tolerant
(`additionalProperties: true`, unknown fields ignored). This ADR spends that
reservation for the *environment* half, and only the declarative half.

## Decision

Add an **optional**, graph-level `environment` block. Absent → the graph is
exactly what it is today (stdlib only, no host files, no network).

```jsonc
"environment": {
  "dependencies": [{"name": "sympy", "version": "1.13.*"}], // default [] = stdlib only
  "mounts":       [{"path": "readings.csv", "mode": "ro"}], // default [] = no fs outside scratch cwd
  "network":      "none"                                    // default "none"; only value allowed in v1
}
```

1. **Declarative — the *what*, never the *how*.** The block names *what* the
   graph requires (these packages, these paths, this network posture). It says
   nothing about *how* that is provided — no venv path, no image, no bind-mount
   syntax, no installer command. The mechanism (subprocess + ephemeral `uv`
   venv + a mount guard, today) is an enforcement-layer detail that can change
   without touching a saved graph or bumping the schema. A graph authored now
   stays valid if C2–C5 later swap `uv` for something else.

2. **Defaults deny.** Every field defaults to the most restrictive value:
   `dependencies: []` (stdlib only), `mounts: []` (no filesystem access outside
   the run's scratch cwd), `network: "none"`. Access is granted only by an
   explicit declaration. A graph that says nothing gets nothing.

3. **`network` is a closed enum, `"none"` only, in v1.** The field exists so the
   *shape* is stable and a future `"restricted"`/`"full"` is an additive value,
   not a new field. v1 validation rejects anything but `"none"` — we do not ship
   a value we cannot yet enforce.

4. **`mount.mode` is `"ro"` | `"rw"`.** Read-only is the ordinary case (a CSV a
   source node reads); `"rw"` is opt-in for nodes that emit files. Paths are
   relative to the run's scratch working directory; the mount guard (C-stream)
   will resolve and confine them.

5. **Schema-tolerant, per ADR 0001 decision 7.** `environment` and every nested
   object keep `additionalProperties: true`; unknown keys are ignored. Adding a
   field later (e.g. `dependencies[].extras`) is a MINOR bump, not a break.

6. **Round-trips byte-for-byte when absent.** `Graph.to_dict()` **omits**
   `environment` entirely when it is `None` (it does not emit `"environment":
   null`). Existing graphs and the committed golden snapshots in
   `engine/schemas/example.*.json` are unchanged by this PR.

## Explicitly deferred — ENFORCEMENT is a later PR (C2–C5)

**This PR adds the descriptor and its validation only. Nothing here installs a
package, opens a file, or restricts the network.** The engine still runs graphs
in-process (`execute.py` is untouched). Concretely, later streams own:

- **C2–C3** — a subprocess runner against an **ephemeral `uv` venv** built from
  `dependencies`.
- **C4** — the **mount guard**: resolve `mounts` against the scratch cwd, deny
  every other path, honour `ro`/`rw`.
- **C5** — network posture wiring (still `"none"` until there is something to
  loosen it to).

**v1 is accident-proof, not malice-proof.** With no enforcement wired in, the
descriptor prevents *accidents* — it documents intent and lets the API reject a
graph whose declared needs it cannot yet satisfy — but it is **not** a security
boundary. A hostile graph is not contained until the C-stream runner lands, and
even then the threat model is honest-mistake isolation, not adversarial
sandboxing. Do not treat the presence of an `environment` block as a guarantee
that anything is confined.

## Consequences

- `GRAPH_SCHEMA` grows an optional `environment` property; `validate_graph`
  checks its shape when present (dependency/mount shapes, `mode` enum,
  `network` must equal `"none"`) and tolerates its absence.
- `Graph` gains an optional `environment: dict | None` field, parsed in
  `from_dict` and emitted from `to_dict` **only when set**.
- No schema-version bump is required (additive optional field, ADR 0001
  decision 7). The engine and example remain pure standard library.
