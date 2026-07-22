"""Demo wiring — give the app real data to serve.

Importing ``examples/minimal/minimal.py`` registers its ``@node`` types on the
default registry. Per ADR 0004 D2/D4 the module is the source of truth, so the
sample graph is the **AST parse** of its ``@main`` composite (node id =
variable name) — the same projection ``PUT /api/graph`` writes back through.
The ``read_values`` path literal is made absolute so ``/api/run`` works
regardless of the process's working directory. The example lives outside the
installed packages, so we add its directory to ``sys.path``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from engine import DEFAULT_REGISTRY

from .workspace import Workspace

_MINIMAL_DIR = Path(__file__).resolve().parents[1] / "examples" / "minimal"


def make_minimal_workspace() -> Workspace:
    """Import the minimal example and bind a workspace to its module."""
    if str(_MINIMAL_DIR) not in sys.path:
        sys.path.insert(0, str(_MINIMAL_DIR))
    import minimal  # noqa: F401  — import side effect registers minimal.* @node types

    return Workspace(DEFAULT_REGISTRY, "minimal")


def load_minimal_graph(workspace: Workspace | None = None) -> dict:
    """Parse the minimal module's composite into engine graph JSON."""
    ws = workspace or make_minimal_workspace()
    doc = ws.parse_graph()
    for node in doc["nodes"]:
        # Absolute CSV path so the demo runs from any cwd (demo-only override;
        # a graph save will persist whatever literal is in the graph).
        if node["type"] == "minimal.read_values" and "path" in node["inputs"]:
            node["inputs"]["path"] = str(_MINIMAL_DIR / "readings.csv")
    return doc
