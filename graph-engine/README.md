# graph-engine

**Phase 0 of the graph-based Python calculation IDE — isolated here, and fully
self-contained** (no runtime dependencies, no reference to any other project).

## What's here

| Path | Role |
|---|---|
| [`engine/`](engine/) | The headless core: `node_spec`, `Graph`, `run`, `to_python`, plus the decorator/tracing authoring layer (`node`, `graph`, `main`). **Pure standard library.** See [`engine/README.md`](engine/README.md). |
| `examples/minimal/` | The smallest end-to-end graph: read a file → two processors → a rendered HTML card. Authored with decorators. |
| `freeze_schemas.py` | Writes the golden example snapshots to `engine/schemas/` (and the schema contract on demand, `--contract`). |
| `tests/` | 15 tests: introspection, schema, run, tracing, and the graph→Python round-trip. |

## Author a graph as ordinary Python

```python
from engine import node, main, run, to_python

@node
def read_values(path: str = "readings.csv") -> list: ...
@node
def total(values: list) -> float: ...
@node
def average(values: list) -> float: ...
@node
def render_summary(total: float, average: float) -> str: ...

@main                                    # a composite node, flagged as the entry/view
def readings_report(path: str = "readings.csv") -> str:
    values = read_values(path)           # calling a node under trace records wiring
    return render_summary(total(values), average(values))

g = readings_report.to_graph()           # -> the engine's Graph data model
run(g).value(g.output_id)                # execute
to_python(g)                             # emit the equivalent flat script
```

Calling a node inside a `@main`/`@graph` composite **records** the wiring instead
of executing; tracing produces the same `Graph` as the low-level builder, so the
frozen JSON contract and `run`/`to_python` are unchanged. `main` is just
`graph(entry=True)` — the entry flag names the default view, nothing more.

## Run it

```bash
cd graph-engine
uv sync --extra dev
uv run python examples/minimal/minimal.py   # run the graph + print exported Python
uv run --extra dev pytest tests/ -q         # 15 passing
uv run python freeze_schemas.py             # regenerate example snapshots
```

## Notes

- **Self-contained:** the engine and the example are stdlib-only; nothing here
  reaches into another directory. (The earlier structural-beam example, which
  linked the sibling `nodezator-structural-demo/demolib`, has been removed.)
- **Schemas:** `engine/schema.py` is the source of truth for the node-spec /
  graph contract. Committed `engine/schemas/example.*.json` are golden snapshots
  (a regression test). The contract JSON is regenerated on demand
  (`freeze_schemas.py --contract`) when a non-Python consumer needs it.
- **Not a wrapper over Nodezator:** this is a clean-room reimplementation of its
  model; the graph JSON is not `.ndz`. Fidelity options remain open — see the
  project `ROADMAP.md`.
