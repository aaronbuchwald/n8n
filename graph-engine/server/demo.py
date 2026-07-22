"""Demo wiring — give the app real data to serve.

Importing ``examples/minimal/minimal.py`` registers its ``@node`` types on the
default registry and its ``@main`` composite traces into a graph. We serve that
graph (with an absolute CSV path, via ``build_graph()``, so ``/api/run`` works
regardless of the process's working directory) as the sample graph. The example
lives outside the installed packages, so we add its directory to ``sys.path``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_MINIMAL_DIR = Path(__file__).resolve().parents[1] / "examples" / "minimal"


def load_minimal_graph() -> dict:
    """Import the minimal example (registering ``minimal.*`` on the default
    registry) and return its traced graph as engine graph JSON."""
    if str(_MINIMAL_DIR) not in sys.path:
        sys.path.insert(0, str(_MINIMAL_DIR))
    import minimal  # noqa: E402  — import side effect registers minimal.* @node types

    return minimal.build_graph().to_dict()
