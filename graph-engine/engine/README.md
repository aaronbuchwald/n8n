# `engine/` — the headless graph core (Phase 0)

A **UI-agnostic** extraction of Nodezator's model: introspect Python callables
into node specs, hold a graph as data, execute it, and emit runnable Python.
Pure standard library — no pygame, no web framework, no calc libraries. Any UI
(pygame today, ReactFlow/VS Code later) drives the *same* core.

## The four entry points

```python
from engine import node_spec, Graph, run, to_python
```

| Entry point | What it does |
|---|---|
| `node_spec(fn)` | Introspect a callable → JSON node spec: **params → input sockets** (+ widget from type/default), **return annotation → output socket(s)** (a list-of-dicts annotation ⇒ multiple named outputs), **docstring → node documentation**. |
| `Graph` | Nodes + edges as plain, serialisable data. Load from JSON (`Graph.from_json`) or build fluently (`.add(...).connect(...)`). Positions are UI-only. |
| `run(graph)` | Execute by a deterministic topological sweep (Kahn; parents before children). Returns an `ExecutionResult` with every socket value. |
| `to_python(graph)` | Emit a flat script: one `_<id> = call(...)` per node, connections → variable refs, widget values → `repr()` literals, node imports at the top. Run it and you reproduce the graph **without the engine** — the round-trip guarantee. |

## Authoring layer: graphs as ordinary Python

```python
from engine import node, graph, main, trace
```

| Decorator | Meaning |
|---|---|
| `@node` | A **primitive** node type — registers + introspects the callable. Under a trace, calling it records a node and returns a `NodeHandle`; called normally it just runs. |
| `@graph` | A **composite** — its body wires other nodes. `.to_graph()` traces it into a `Graph`. Composites are *inlined* on trace, so `run`/`to_python` only ever see primitives (flatten-by-default). |
| `@main` | `graph(entry=True)` — a composite flagged as the default view. `main` is not a distinct concept; **everything is a node**, and a composite rendered as a graph *is* its traced subgraph. |

Imperative logic (loops, branches, mutation) lives inside a `@node` body;
composites are pure dataflow. Branching on a traced value raises `TracingError`.

`NodeRegistry` still binds type names → `(callable, spec)` under the hood
(populated by `@node`); it stays available for building nodes explicitly.

## The contract (JSON schema)

Version **`0.1.0`** (`engine.SCHEMA_VERSION`). Source of truth is
**`engine/schema.py`** (`NODE_SPEC_SCHEMA`, `GRAPH_SCHEMA`, `validate_node_spec`,
`validate_graph`). We commit **golden snapshots**, not the contract docs:

- [`schemas/example.node-specs.json`](schemas/example.node-specs.json) — the specs of the example nodes.
- [`schemas/example.graph.json`](schemas/example.graph.json) — the example graph.

Regenerate snapshots with `uv run python freeze_schemas.py`; emit the contract
docs on demand with `freeze_schemas.py --contract` (for the Phase-4 frontend).

### node-spec shape
```jsonc
{
  "name": "render_summary", "title": "render_summary", "callName": "render_summary",
  "doc": "Render a small, self-contained HTML card …",
  "inputs": [
    { "name": "total", "type": "float", "required": true, "default": null,
      "widget": { "kind": "number", "subtype": "float" } }
  ],
  "outputs": [ { "name": "output", "type": "str" } ],
  "imports": { "stdlib": null, "thirdParty": "from minimal import render_summary" }
}
```
`widget` is `{"kind": "number"|"text"|"checkbox", "subtype"?}` for scalar inputs,
or `null` when an input must be wired. A list-of-dicts return annotation yields
multiple named output sockets.

### graph shape
```jsonc
{
  "version": "0.1.0",
  "nodes": [
    { "id": "read_values", "type": "read_values",
      "inputs": { "path": "readings.csv" }, "position": null }
  ],
  "edges": [
    { "source": "read_values", "sourceOutput": "output",
      "target": "total", "targetInput": "values" }
  ]
}
```

## Try it
```bash
uv run python examples/minimal/minimal.py   # run the example graph + print exported Python
uv run --extra dev pytest tests/ -q         # 15 tests
uv run python freeze_schemas.py             # regenerate example snapshots
```
