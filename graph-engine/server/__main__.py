"""Run the server:  uv run --extra demo python -m server [--library pkg.mod] [--port 8000]

(``--extra demo`` covers the default showcase; ``--extra server`` is enough only
with ``--no-demo`` or a dep-free ``--library``.)

``--library`` imports a module so its ``@node`` registrations populate the
default registry (the fuller loader is stream A3). Without it, the palette is
whatever has already been registered in-process.

``--demo`` (the default) loads the bundled *showcase* example so the app has a
real palette **and** a sample graph that surfaces every editable widget kind
(math, table-recipe, text, number) at ``GET /api/graph``. Pass ``--no-demo`` for
an empty registry, or ``--library`` to load your own types. Running the showcase
executes ``sym.*`` nodes, so it needs those deps — use the ``demo`` extra, which
bundles the server + sym deps in one:
``uv run --extra demo python -m server --demo``.
(Without the sym deps the server still starts and lists specs — lazy imports —
but a run fails with ``ModuleNotFoundError: No module named 'sympy'``.)

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
from .demo import DEFAULT_EXAMPLE, EXAMPLES, example_dir, load_graph, make_workspace


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
        help="serve a bundled example's specs + sample graph (default: on)",
    )
    parser.add_argument(
        "--example",
        default=DEFAULT_EXAMPLE,
        choices=sorted(EXAMPLES),
        help="which bundled program to serve + display (default: %(default)s)",
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

    # Select which program to serve. `--demo` on → the `--example` program;
    # off → nothing (empty registry). Everything is generic off the example
    # name, so pointing at a different program is just `--example NAME`.
    if args.demo:
        workspace = make_workspace(args.example)
        sample_graph = load_graph(args.example, workspace)
        # Relative CSV `path`s resolve against the example's dir at /api/run only;
        # the served/persisted graph keeps them relative (review 0005 #3).
        run_base_dir = example_dir(args.example)
    else:
        workspace = sample_graph = run_base_dir = None

    # Preflight: if the served program runs sym.* nodes, its deps are lazy-imported,
    # so without them the server starts and lists specs but a run fails deep in the
    # browser with a bare ModuleNotFoundError. Catch it here with the exact fix.
    if sample_graph is not None and any(n["type"].startswith("sym.") for n in sample_graph["nodes"]):
        import importlib.util

        missing = [
            m
            for m in ("sympy", "handcalcs", "forallpeople", "latex2mathml")
            if importlib.util.find_spec(m) is None
        ]
        if missing:
            print(
                f"\n✗ The '{args.example}' program runs symbolic-math nodes that need extra\n"
                f"  deps, and these are missing: {', '.join(missing)}.\n\n"
                f"  Re-run with the `demo` extra (bundles the server + sym deps):\n\n"
                f"      uv run --extra demo python -m server --example {args.example}\n\n"
                f"  (Use --no-demo to serve an empty registry without them.)\n",
                file=sys.stderr,
            )
            raise SystemExit(1)

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
        create_app(sample_graph=sample_graph, workspace=workspace, run_base_dir=run_base_dir),
        host=args.host,
        port=args.port,
    )


if __name__ == "__main__":
    main()
