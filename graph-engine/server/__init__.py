"""HTTP service exposing the engine's entry points (ADR 0002 — Seam 1).

The five engine operations, verbatim over HTTP, so any UI drives the *same*
core:

    GET  /api/specs                 -> registry.specs()   (the palette)
    POST /api/graphs/validate       -> bind()             (validate-on-connect)
    POST /api/run                   -> run()
    POST /api/export                -> to_python()
    GET/PUT /api/source/{spec_id}   -> 501 (reserved for stream E)

The graph payload is the engine's existing graph JSON — no new format. Values
are JSON-serialised with a ``{"$repr","$type"}`` fallback for non-JSON returns.
"""

from .app import create_app

__all__ = ["create_app"]
