"""Demo wiring — pick which program the server serves and displays.

Any bundled example under ``examples/<name>/`` whose module defines an ``@main``
composite can be served: the sample graph is the **AST parse** of that composite
(ADR 0004 D2/D4, node id = variable name) — the same projection ``PUT
/api/graph`` writes back through — and the app binds a :class:`Workspace` to the
module so ``/api/source`` + ``PUT /api/graph`` edit its real ``.py``.

The graph is served **pristine**: relative CSV ``path`` literals stay exactly
what the module authors (e.g. ``"forces.csv"``). ``create_app`` resolves them
against the program's own directory only on ``/api/run`` (via ``run_base_dir``),
so nothing machine-specific is ever persisted (review 0005 #3) — and this is
modular: a program with any number of file reads just works.

``--example NAME`` selects the program; ``--demo`` serves the default. Pointing
at a new program is one :data:`EXAMPLES` entry away — everything around it
(workspace, run-path resolution, source editing) is generic.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from engine import DEFAULT_REGISTRY

from .workspace import Workspace

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples"

# name -> the example's directory. Its module is ``<name>.py`` inside it, and its
# ``@main`` composite is what gets served. Add an entry to serve a new program.
EXAMPLES: dict[str, Path] = {
    "showcase": _EXAMPLES / "showcase",
    "capacity_check": _EXAMPLES / "capacity_check",
    "capacity_check_split": _EXAMPLES / "capacity_check_split",
    "beam_bearing_pressure": _EXAMPLES / "beam_bearing_pressure",
    "beam_bearing_pressure_rfem": _EXAMPLES / "beam_bearing_pressure_rfem",
    "handcalc_demo": _EXAMPLES / "handcalc_demo",
    "minimal": _EXAMPLES / "minimal",
}
DEFAULT_EXAMPLE = "showcase"


def example_dir(name: str) -> Path:
    """The directory of bundled example ``name`` (its ``run_base_dir``)."""
    try:
        return EXAMPLES[name]
    except KeyError:
        raise KeyError(f"unknown example {name!r}; choose from {sorted(EXAMPLES)}") from None


def make_workspace(name: str = DEFAULT_EXAMPLE) -> Workspace:
    """Import example ``name`` and bind a workspace to its module.

    Importing the module registers its ``@node`` types **and** any node pack it
    imports (e.g. ``table``/``sym``) — the palette the served graph resolves
    against. The example's directory is added to ``sys.path`` first.
    """
    directory = example_dir(name)
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    importlib.import_module(name)  # side effect: registers <name>.* (+ imported packs)
    return Workspace(DEFAULT_REGISTRY, name)


def load_graph(name: str = DEFAULT_EXAMPLE, workspace: Workspace | None = None) -> dict:
    """Parse example ``name``'s ``@main`` composite into engine graph JSON, as authored."""
    ws = workspace or make_workspace(name)
    return ws.parse_graph()


# --- back-compat thin wrappers (existing callers/tests) --------------------
def make_showcase_workspace() -> Workspace:
    return make_workspace("showcase")


def load_showcase_graph(workspace: Workspace | None = None) -> dict:
    return load_graph("showcase", workspace)


def make_minimal_workspace() -> Workspace:
    return make_workspace("minimal")


def load_minimal_graph(workspace: Workspace | None = None) -> dict:
    return load_graph("minimal", workspace)
