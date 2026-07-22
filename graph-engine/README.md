# graph-engine

**Phase 0 of the graph-based Python calculation IDE — isolated here so the new
work is separable from everything that came before.**

This directory is self-contained. The one exception is the *example* domain
functions, which are imported from the original demo next door
(`../nodezator-structural-demo/demolib`) rather than duplicated — see
[Cross-reference](#the-one-cross-reference) below.

## What's here

| Path | Role |
|---|---|
| [`engine/`](engine/) | The headless core: `node_spec`, `Graph`, `run`, `to_python`, `NodeRegistry`. **Pure standard library.** See [`engine/README.md`](engine/README.md) for the contract + frozen JSON schemas. |
| `demo_graph.py` | Registers the seven example functions as nodes and builds the beam graph as engine data. |
| `freeze_schemas.py` | Writes the frozen schemas + examples to `engine/schemas/`. |
| `tests/` | 12 tests: introspection, schema validation, execution vs. baseline, graph→Python round-trip. |

## Run it

```bash
cd graph-engine
uv sync --extra dev
uv run python demo_graph.py            # run the beam graph + print exported Python
uv run --extra dev pytest tests/ -q    # 12 passing
uv run python freeze_schemas.py        # regenerate engine/schemas/*.json
```

## The one cross-reference

The engine is domain-agnostic; to *demonstrate* it we wrap real functions. Those
functions (`read_members_csv`, `axial_stress`, `render_stress_check`, …) already
exist in `../nodezator-structural-demo/demolib`. Rather than copy them, the demo
bridge and tests put that sibling directory on `sys.path` (via `demo_graph.py`
and the `pythonpath` in `pyproject.toml`). So:

- **`engine/` depends on nothing outside itself** (stdlib only).
- **`demo_graph.py` + `tests/` depend on the sibling `demolib`** — the only tie
  back to the pre-existing code. Everything genuinely new lives in this folder.

## What this is *not* (yet)

This is a clean-room reimplementation of Nodezator's model, **not** a wrapper
over Nodezator. Our graph JSON is not `.ndz`, and the engine does not import
Nodezator. Fidelity options (loading the real `demo_nodepack/` folders, `.ndz`
round-trip) are open decisions — see the project `ROADMAP.md`.
