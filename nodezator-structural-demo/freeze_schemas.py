"""Write the frozen JSON schemas and example artifacts to ``engine/schemas/``.

Run after changing :mod:`engine.schema` or the demo node pack::

    uv run python freeze_schemas.py

The committed files are the reviewable, out-of-band copy of the Phase-0
contract; a test asserts they stay in sync with the in-code definitions.
"""

from __future__ import annotations

import json
from pathlib import Path

from engine import GRAPH_SCHEMA, NODE_SPEC_SCHEMA
from demo_graph import build_graph, build_registry

OUT = Path(__file__).resolve().parent / "engine" / "schemas"


def _write(name: str, data: object) -> None:
    path = OUT / name
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(OUT.parent.parent)}")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # The frozen contract.
    _write("node-spec.schema.json", NODE_SPEC_SCHEMA)
    _write("graph.schema.json", GRAPH_SCHEMA)

    # Concrete examples that validate against the contract.
    registry = build_registry()
    _write("example.node-specs.json", registry.specs())
    _write("example.beam-graph.json", build_graph(index=0).to_dict())


if __name__ == "__main__":
    main()
