# `engine/` — the headless graph core (Phase 0)

A **UI-agnostic** extraction of Nodezator's model: introspect Python callables
into node specs, hold a graph as data, validate + run it, and emit runnable
Python. Pure standard library. Design rationale: [`../docs/adr/0001-engine-core-design.md`](../docs/adr/0001-engine-core-design.md).

## Entry points

```python
from engine import node_spec, Graph, bind, run, to_python
```

| Entry point | What it does |
|---|---|
| `node_spec(fn)` | Introspect a callable → JSON spec: **params → input sockets** (with `kind` + a widget), **return → one `result` socket** (or named sockets via `outputs=`), **docstring → doc**, **`module.qualname` → a collision-proof id**. |
| `Graph` | Nodes + edges + the `output` socket, as portable, string-keyed data. `O(1)` id lookup; `Graph.from_json` / `to_json`. |
| `bind(graph, registry)` | **The one string→reference step.** Resolves every id/socket/param once and validates the whole graph up front (unknown type, bad socket/param, duplicate input edge, missing required input, non-serialisable literal, cycle). Returns a reference-linked `BoundGraph`. Public — the UI's *validate-on-connect* endpoint. |
| `run(graph)` | `bind` + topological sweep. Honours parameter kinds (positional-only passed positionally); wraps node failures in `NodeExecutionError(node_id)`. |
| `to_python(graph)` | Flat script, one `_id = fn(...)` per node. Imports are **aliased on collision** (`total` / `total_2`), so generated code never clobbers a name. Run it and you reproduce the graph without the engine. |

## Authoring: graphs as ordinary Python

```python
from engine import node, graph, main

@node
def total(values: list) -> float: ...
@node(outputs=["lo", "hi"])            # declare named output sockets (returns a keyed dict)
def bounds(values: list) -> dict: ...

@main                                   # a composite, flagged as the default view
def report(path: str = "readings.csv") -> str:
    ...                                 # calling a node here records wiring, not a call
```

`@node` registers a **primitive** by its `module.qualname` id. `@graph`/`@main`
is a **composite**; `.to_graph()` traces its body (inlining nested composites) to
a `Graph`. `main` is just `graph(entry=True)`. Imperative logic lives inside a
`@node` body; branching on a traced value raises `TracingError`.

## Output model

- Default: one socket named **`result`** carrying the whole return value.
- `@node(outputs=["a", "b"])`: named sockets; the callable returns a dict keyed
  by those names, extracted by name. Dict returns are **not** auto-exploded.
- Wire one output of many with `handle.a` (authoring) or an edge's `sourceOutput`
  (data). Nested access (`obj["k"]["j"]`) is *not* an edge feature — use a `pick`
  node (Phase 1). See the ADR.

## The contract (JSON schema)

Version **`0.2.0`** (`engine.SCHEMA_VERSION`, in `engine/version.py`). Source of
truth is **`engine/schema.py`**; it is **additive-tolerant** (`additionalProperties: true`,
validators ignore unknown fields) so new optional fields are non-breaking. We
commit golden **snapshots**, not the contract docs:

- [`schemas/example.node-specs.json`](schemas/example.node-specs.json), [`schemas/example.graph.json`](schemas/example.graph.json)

Regenerate: `uv run python freeze_schemas.py` (`--contract` also emits the schema docs).

### node-spec shape
```jsonc
{
  "id": "minimal.total", "name": "total", "title": "total",
  "module": "minimal", "qualname": "total", "doc": "Sum the values.",
  "inputs": [ { "name": "values", "type": "list", "kind": "positionalOrKeyword",
               "required": true, "default": null, "widget": null } ],
  "outputs": [ { "name": "result", "type": "float" } ]
}
```
### graph shape
```jsonc
{
  "version": "0.2.0",
  "nodes": [ { "id": "read_values", "type": "minimal.read_values",
               "inputs": { "path": "readings.csv" }, "position": null } ],
  "edges": [ { "source": "read_values", "sourceOutput": "result",
               "target": "total", "targetInput": "values" } ],
  "output": { "node": "render_summary", "socket": "result" }
}
```

## Try it
```bash
uv run python examples/minimal/minimal.py   # run the example graph + print exported Python
uv run --extra dev pytest tests/ -q         # 33 tests
uv run python freeze_schemas.py             # regenerate example snapshots
```
