# `engine/` — the headless graph core (Phase 0)

A **UI-agnostic** extraction of Nodezator's model: introspect Python callables
into node specs, hold a graph as data, execute it, and emit runnable Python.
Pure standard library — no pygame, no web framework, no calc libraries. Any UI
(pygame today, ReactFlow/VS Code later) drives the *same* core.

## The four entry points

```python
from engine import node_spec, Graph, run, to_python, NodeRegistry
```

| Entry point | What it does |
|---|---|
| `node_spec(fn)` | Introspect a callable → JSON node spec: **params → input sockets** (+ widget from type/default), **return annotation → output socket(s)** (a list-of-dicts annotation ⇒ multiple named outputs), **docstring → node documentation**. |
| `Graph` | Nodes + edges as plain, serialisable data. Build fluently (`.add(...).connect(...)`) or load from JSON (`Graph.from_json`). Positions are UI-only. |
| `run(graph, registry)` | Execute by a deterministic topological sweep (Kahn; parents before children — same guarantee as Nodezator's lazy retry). Returns an `ExecutionResult` with every socket value. |
| `to_python(graph, registry)` | Emit a flat script: one `_<id> = call(...)` per node, connections → variable refs, widget values → `repr()` literals, node imports collected at the top. Run it and you reproduce the graph **without the engine** — the round-trip guarantee. |

A `NodeRegistry` binds type names → `(callable, spec)`, kept separate from the
graph so the same graph JSON can be driven by different registries (e.g. swap a
mock RFEM node for the real one — a one-line change).

## The frozen contract (JSON schemas)

Version **`0.1.0`** (`engine.SCHEMA_VERSION`). Everything later depends on these
two shapes; they are versioned data, not code.

- [`schemas/node-spec.schema.json`](schemas/node-spec.schema.json) — one node type.
- [`schemas/graph.schema.json`](schemas/graph.schema.json) — a saved graph.
- [`schemas/example.node-specs.json`](schemas/example.node-specs.json) — the 7 demo nodes.
- [`schemas/example.beam-graph.json`](schemas/example.beam-graph.json) — the beam graph.

In code: `NODE_SPEC_SCHEMA`, `GRAPH_SCHEMA`, `validate_node_spec()`,
`validate_graph()`. Regenerate the files with `uv run python freeze_schemas.py`
(a test asserts they stay in sync).

### node-spec shape

```jsonc
{
  "name": "unpack_member", "title": "unpack_member", "callName": "unpack_member",
  "doc": "Explode one member row into individual scalar output sockets. …",
  "inputs": [
    { "name": "member", "type": "dict", "required": true, "default": null, "widget": null }
  ],
  "outputs": [ { "name": "name", "type": "Any" }, { "name": "force_kN", "type": "Any" }, … ],
  "imports": { "stdlib": null, "thirdParty": "from demolib.data import unpack_member" }
}
```

`widget` is `{"kind": "number"|"text"|"checkbox", "subtype"?: "int"|"float"}`
for scalar inputs, or `null` when an input must be wired.

### graph shape

```jsonc
{
  "version": "0.1.0",
  "nodes": [
    { "id": "csv", "type": "read_members_csv", "inputs": { "path": "members.csv" }, "position": {"x":0,"y":0} },
    { "id": "pick", "type": "select_member", "inputs": { "index": 0 }, "position": {"x":220,"y":0} }
  ],
  "edges": [
    { "source": "csv", "sourceOutput": "output", "target": "pick", "targetInput": "rows" }
  ]
}
```

## Try it

```bash
uv run python demo_graph.py            # run the beam graph + print exported Python
uv run python freeze_schemas.py        # (re)write engine/schemas/*.json
uv run --extra dev pytest tests/ -q    # 12 tests: introspection, schema, run, round-trip
```

`demo_graph.py` registers the seven `demolib` functions as nodes and builds the
same pipeline `run_demo.py` runs by hand — now as engine data.
