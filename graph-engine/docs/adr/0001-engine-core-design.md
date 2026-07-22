# ADR 0001 — Phase-0 engine core: binding, identity, outputs, evolution

Status: accepted (2026-07) · Supersedes the initial ad-hoc model · Scope: `graph-engine/`

Records the design decisions taken after the first review round, so the
trade-offs and the deliberate deferrals aren't re-litigated.

## Context

The engine extracts Nodezator's model into a headless core: introspect Python
functions into node specs, model a graph as data, run it, and export it back to
a flat Python script. Review feedback raised: string-keyed wiring vs. references,
errors caught at run time vs. before, kwargs-only invocation, multi-output
ergonomics, `O(n)` lookups, a fragile multi-output annotation, and whether the
spec should carry the function body + runtime env + a cross-language IPC format.

## Decisions

1. **Two representations, one binding step.** The persisted/wire form (`Graph`,
   JSON) stays **string-keyed** — it's what ReactFlow, HTTP, and diffable VCS
   files need. References live only in an **ephemeral, validated** `BoundGraph`,
   produced by `bind(graph, registry)` — the single place every id/socket/param
   string is resolved, exactly once. `run`/`to_python` consume `BoundGraph`.
   Shape: `Graph` (portable data) → `bind` → `BoundGraph` (reference-linked) —
   the same source→AST→typed-IR split a compiler uses.

2. **Errors are static, not runtime.** `bind` validates the whole graph up front
   (unknown type, bad socket, bad param, duplicate input edge, missing required
   input, non-serialisable literal, cycle) and is public — it's the UI's
   "validate this edit" endpoint on every drag-to-connect. No structural error
   can surface mid-execution.

3. **Collision-proof identity.** A node type's id is `module.qualname`, not its
   bare name, so same-named functions from different packages coexist. The
   registry errors only on a *true* duplicate (same id, different callable;
   `replace=True` to override). The Python emitter **aliases on collision**
   (`total` / `total_2`), so generated scripts never clobber a name either.

4. **Output model.** One `result` socket by default; `@node(outputs=[...])`
   declares named sockets (the callable then returns a dict keyed by them,
   extracted by name). Dict returns are **not** special-cased, and the
   list-of-dicts return-annotation trick is **retired** (it breaks under
   `from __future__ import annotations`, mypy, and PEP 649/749).

5. **Invocation honours parameter kinds.** Each input records its `kind`;
   positional-only params are passed positionally (and emitted positionally),
   the rest by keyword. `*args`/`**kwargs` are rejected at introspection (not
   addressable as named sockets).

6. **The function body is not serialised — deliberately.** The end goal ("your
   graph is ordinary Python; it exports back to a flat script that calls the
   original functions") requires the importable module to be the single source
   of truth. Embedding bodies would create stale copies, an unanswerable
   "which wins?", and an executable-payload security surface. The spec instead
   carries structured `module` + `qualname` identity (replacing the old
   free-text import line). A UI edits the real file, resolved via `module`.

7. **Additive-tolerant schema.** `additionalProperties: true`; validators ignore
   unknown fields; `widget.kind` is an open vocabulary. Adding an optional field
   is a MINOR bump, not a break.

## Deferred (recorded so the door stays open)

- **Formal versioning/migration** (semver ranges, migrations, `0.x` policy
  enforcement) — until backwards-compat first matters. The additive-tolerant
  schema (decision 7) means this is not a redesign later, just new code.
- **`implementation` / runtime-env block** (`{language, runtime, image, …}`) —
  a Phase-4 *execution-target* concern, not a Phase-0 spec field. Reserve the
  optional key; define it when an executor **service** exists.
- **IPC value serialisation & cross-language nodes** — a property of the Phase-4
  *run API* (JSON values + opaque server-side handles for large values like
  DataFrames), not of the node-spec. Cross-language is YAGNI until a feature
  needs it.
- **Nested output access** (`obj["stats"]["mean"]`) — via a stdlib `pick` node
  (Phase 1) and, later, tracing sugar. **Never** paths-on-edges.
- **Tuple-positional multi-output** — today multi-output extracts by dict key;
  positional tuple extraction is a later nicety.
- **Stable, diff-friendly node ids** — trace ids are call-order dependent
  (`total_2` shifts if a call is inserted above), which will make Phase-6
  semantic diffs noisy. Solve when VCS lands (content-hash or explicit `id=`).

## Consequences

- `run(graph)` = `bind` + sweep; `bind` is reusable by any UI/validator.
- Graph JSON grew an optional `output` field and node `type`s are now qualified
  ids; specs gained `id`/`module`/`qualname`/`kind` and lost the free-text
  `imports`. Schema version → `0.2.0`.
- The engine and example remain pure standard library.
