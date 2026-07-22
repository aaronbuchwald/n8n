"""Run the server:  uv run --extra server python -m server [--library pkg.mod] [--port 8000]

``--library`` imports a module so its ``@node`` registrations populate the
default registry (the fuller loader is stream A3). Without it, the palette is
whatever has already been registered in-process.

``--demo`` (the default) loads the bundled *minimal* example so the app has a
real palette **and** a sample graph to render at ``GET /api/graph``. Pass
``--no-demo`` for an empty registry, or ``--library`` to load your own types.
"""

from __future__ import annotations

import argparse
import importlib

import uvicorn

from .app import create_app
from .demo import load_minimal_graph


def main() -> None:
    parser = argparse.ArgumentParser(prog="server")
    parser.add_argument("--library", action="append", default=[], help="module(s) to import for their @node types")
    parser.add_argument(
        "--demo",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="serve the bundled minimal example's specs + sample graph (default: on)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    for module in args.library:
        importlib.import_module(module)

    sample_graph = load_minimal_graph() if args.demo else None

    uvicorn.run(create_app(sample_graph=sample_graph), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
