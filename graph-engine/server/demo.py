"""Demo wiring — give the app real data to serve.

Importing an example module registers its ``@node`` types on the default
registry. Per ADR 0004 D2/D4 the module is the source of truth, so the sample
graph is the **AST parse** of its ``@main`` composite (node id = variable name)
— the same projection ``PUT /api/graph`` writes back through. CSV ``path``
literals are made absolute so ``/api/run`` works regardless of the process's
working directory (a demo-only override; a graph save persists whatever literal
is in the graph). Examples live outside the installed packages, so we add each
one's directory to ``sys.path``.

Two demos:

* **showcase** (the default, ADR 0005) — surfaces every editable widget kind
  (math, table-recipe, text, number) so opening the app shows live editors.
* **minimal** — the smallest end-to-end graph; kept for the focused tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

from engine import DEFAULT_REGISTRY

from .workspace import Workspace

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
_MINIMAL_DIR = _EXAMPLES / "minimal"
_SHOWCASE_DIR = _EXAMPLES / "showcase"


def _abs_csv_paths(doc: dict, node_type: str, csv_path: Path) -> None:
    """Rewrite ``path`` literals of ``node_type`` to an absolute CSV path."""
    for node in doc["nodes"]:
        if node["type"] == node_type and "path" in node["inputs"]:
            node["inputs"]["path"] = str(csv_path)


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
    _abs_csv_paths(doc, "minimal.read_values", _MINIMAL_DIR / "readings.csv")
    return doc


def make_showcase_workspace() -> Workspace:
    """Import the showcase example and bind a workspace to its module.

    Importing ``showcase`` pulls in the ``table`` and ``sym`` packs (its own
    imports), so their ``@node`` types are registered too — the palette the
    editable widgets resolve against.
    """
    if str(_SHOWCASE_DIR) not in sys.path:
        sys.path.insert(0, str(_SHOWCASE_DIR))
    import showcase  # noqa: F401  — import side effect registers showcase/table/sym @node types

    return Workspace(DEFAULT_REGISTRY, "showcase")


def load_showcase_graph(workspace: Workspace | None = None) -> dict:
    """Parse the showcase module's composite into engine graph JSON."""
    ws = workspace or make_showcase_workspace()
    doc = ws.parse_graph()
    _abs_csv_paths(doc, "table.read_table", _SHOWCASE_DIR / "showcase.csv")
    return doc
