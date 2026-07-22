"""Run the server:  uv run --extra server python -m server [--library pkg.mod] [--port 8000]

``--library`` imports a module so its ``@node`` registrations populate the
default registry (the fuller loader is stream A3). Without it, the palette is
whatever has already been registered in-process.

``--demo`` (the default) loads the bundled *minimal* example so the app has a
real palette **and** a sample graph to render at ``GET /api/graph``. Pass
``--no-demo`` for an empty registry, or ``--library`` to load your own types.

**Enter to open:** when stdin is a TTY, the server prints a hint and — on the
first Enter — opens the app view (``http://{host}:{port}/``) in your browser.
Build the web first (``cd web && pnpm build``) so ``/`` serves the SPA rather
than 404. Use ``--no-open`` to disable, or ``--open-url URL`` to point at a web
dev server on another port (e.g. ``pnpm dev``).
"""

from __future__ import annotations

import argparse
import importlib
import sys
import threading
import webbrowser

import uvicorn

from .app import WEB_DIST, create_app
from .demo import load_minimal_graph, make_minimal_workspace


def view_url(host: str, port: int) -> str:
    """The single same-origin URL that serves the app view."""
    return f"http://{host}:{port}/"


def _wait_for_enter_then_open(url: str) -> None:
    """Block on stdin; open ``url`` in the browser on the first empty line.

    Runs in a daemon thread. Never crashes the server: any error (EOF, a closed
    stdin) just ends the loop quietly.
    """
    try:
        for line in sys.stdin:
            if line.strip() == "":
                webbrowser.open(url)
                return
    except Exception:
        return


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
    parser.add_argument(
        "--open",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="press Enter in the terminal to open the app view in your browser (default: on when interactive)",
    )
    parser.add_argument(
        "--open-url",
        default=None,
        help="URL to open on Enter (default: http://{host}:{port}/); e.g. a web dev server started with pnpm dev",
    )
    args = parser.parse_args()

    for module in args.library:
        importlib.import_module(module)

    workspace = make_minimal_workspace() if args.demo else None
    sample_graph = load_minimal_graph(workspace) if args.demo else None

    url = args.open_url or view_url(args.host, args.port)

    # Be LOUD about whether the built web app is present, so opening the printed
    # URL never comes as a surprise 404. Printed on every run (not just a TTY).
    web_built = WEB_DIST.is_dir()
    if web_built:
        print(f"✓ web/dist found — the app is served at {url}")
    else:
        print(
            "✗ web/dist NOT built — run: cd web && pnpm build\n"
            f"  Until then {url} shows a build hint (the /api/* endpoints work now)."
        )

    # Enter-to-open only when interactive; skip for pipes/CI/tests so we never
    # block on a stdin that will never see a keystroke.
    if args.open and sys.stdin.isatty():
        if web_built:
            print(f"➜ Press Enter to open the app in your browser ({url})")
        else:
            print(
                f"➜ Press Enter to open the app in your browser ({url}) — "
                "it will show a build hint until you build the web (`cd web && pnpm build`)"
            )
        threading.Thread(target=_wait_for_enter_then_open, args=(url,), daemon=True).start()

    uvicorn.run(
        create_app(sample_graph=sample_graph, workspace=workspace),
        host=args.host,
        port=args.port,
    )


if __name__ == "__main__":
    main()
