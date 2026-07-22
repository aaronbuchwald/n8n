"""Demo wiring — give the app real data to serve.

Importing an example module registers its ``@node`` types on the default
registry. Per ADR 0004 D2/D4 the module is the source of truth, so the sample
graph is the **AST parse** of its ``@main`` composite (node id = variable name)
— the same projection ``PUT /api/graph`` writes back through, and it is served
**pristine**: CSV ``path`` literals stay exactly what the module authors (e.g.
a relative ``"showcase.csv"``), never rewritten here. ``*_RUN_PATH_OVERRIDES``
below is passed to ``create_app(run_path_overrides=...)`` instead, so the
absolute path only ever exists on the copy of the graph ``/api/run`` executes
— the served graph, and anything a widget commit persists back through
``PUT /api/graph``, never sees it (review 0005 #3). Examples live outside the
installed packages, so we add each one's directory to ``sys.path``.

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

# node type -> absolute CSV path, for `create_app(run_path_overrides=...)`.
# Run-time only (see module docstring) — never applied to the served/persisted
# graph itself.
MINIMAL_RUN_PATH_OVERRIDES: dict[str, str] = {
    "minimal.read_values": str(_MINIMAL_DIR / "readings.csv"),
}
SHOWCASE_RUN_PATH_OVERRIDES: dict[str, str] = {
    "table.read_table": str(_SHOWCASE_DIR / "showcase.csv"),
}


def make_minimal_workspace() -> Workspace:
    """Import the minimal example and bind a workspace to its module."""
    if str(_MINIMAL_DIR) not in sys.path:
        sys.path.insert(0, str(_MINIMAL_DIR))
    import minimal  # noqa: F401  — import side effect registers minimal.* @node types

    return Workspace(DEFAULT_REGISTRY, "minimal")


def load_minimal_graph(workspace: Workspace | None = None) -> dict:
    """Parse the minimal module's composite into engine graph JSON, as authored."""
    ws = workspace or make_minimal_workspace()
    return ws.parse_graph()


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
    """Parse the showcase module's composite into engine graph JSON, as authored."""
    ws = workspace or make_showcase_workspace()
    return ws.parse_graph()
