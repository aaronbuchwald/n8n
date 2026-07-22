"""FastAPI application wiring the engine to HTTP (see package docstring)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# The production web bundle, if it has been built (`cd web && pnpm build`).
WEB_DIST = Path(__file__).resolve().parents[1] / "web" / "dist"

from engine import (
    DEFAULT_REGISTRY,
    SCHEMA_VERSION,
    EngineError,
    Graph,
    NodeExecutionError,
    NodeRegistry,
    bind,
    run,
    to_python,
    validate_graph,
)

from .serialize import to_jsonable


def _error_payload(exc: Exception) -> dict:
    """Structured error: ``{code, message, nodeId?, edge?, nodeIds?}``.

    The optional fields appear only when the exception exposes them, so the
    common ``{code, message}`` shape is unchanged:

    * ``nodeId`` — a single offending node (bind errors, ``NodeExecutionError``).
    * ``edge`` — the offending connection ``{source, sourceOutput, target,
      targetInput}`` for edge-scoped bind errors.
    * ``nodeIds`` — the ids caught in a cycle (``CycleError``).
    """
    payload: dict[str, Any] = {"code": type(exc).__name__, "message": str(exc)}
    node_id = getattr(exc, "node_id", None)
    if node_id is not None:
        payload["nodeId"] = node_id
    edge = getattr(exc, "edge", None)
    if edge is not None:
        payload["edge"] = edge
    node_ids = getattr(exc, "node_ids", None)
    if node_ids:
        payload["nodeIds"] = node_ids
    return payload


def _graph_from(body: dict) -> Graph:
    """Accept either ``{"graph": {...}}`` or a bare graph object."""
    raw = body.get("graph", body) if isinstance(body, dict) else body
    validate_graph(raw)  # shape + referential integrity (raises SchemaError)
    return Graph.from_dict(raw)


def create_app(
    registry: Optional[NodeRegistry] = None,
    sample_graph: Optional[Any] = None,
    web_dist: Optional[Path] = WEB_DIST,
) -> FastAPI:
    """Build the app over ``registry`` (defaults to the process registry).

    ``sample_graph`` — an engine ``Graph`` or its JSON dict — is served by
    ``GET /api/graph`` so a client has something to render. Its node ``type``s
    must all exist in ``registry`` (``GET /api/specs``). ``None`` → the endpoint
    replies 404.

    ``web_dist`` — if the directory exists, the built web app is mounted at
    ``/`` (``html=True``) so the SPA is served **same-origin** with ``/api/*``
    (the web already fetches relative ``/api/*``). It is mounted **last** so it
    never shadows an ``/api`` route. Pass ``None`` (or point at a missing dir)
    to skip the mount — e.g. when the web is served separately via ``pnpm dev``.
    """
    registry = registry or DEFAULT_REGISTRY
    # Normalise to the engine graph JSON dict once; accept a Graph or a dict.
    graph_doc: Optional[dict] = sample_graph.to_dict() if isinstance(sample_graph, Graph) else sample_graph
    app = FastAPI(title="graph-engine", version=SCHEMA_VERSION)

    @app.get("/api/specs")
    def get_specs() -> dict:
        return {"version": SCHEMA_VERSION, "specs": registry.specs()}

    @app.get("/api/graph")
    def get_graph() -> JSONResponse:
        if graph_doc is None:
            return JSONResponse(status_code=404, content={"message": "no sample graph is configured"})
        return JSONResponse(status_code=200, content=graph_doc)

    @app.post("/api/graphs/validate")
    def validate(body: dict = Body(...)) -> JSONResponse:
        try:
            bind(_graph_from(body), registry)
        except EngineError as exc:
            return JSONResponse(status_code=422, content={"ok": False, "errors": [_error_payload(exc)]})
        return JSONResponse(status_code=200, content={"ok": True})

    @app.post("/api/run")
    def run_graph(body: dict = Body(...)) -> dict:
        try:
            graph = _graph_from(body)
        except EngineError as exc:
            raise HTTPException(status_code=422, detail=[_error_payload(exc)]) from exc
        try:
            result = run(graph, registry)  # environment honoured by stream C later
        except NodeExecutionError as exc:
            # Keep the documented response shape on failure (ADR 0002).
            return {"outputs": {}, "order": [], "output": graph.output, "errors": [_error_payload(exc)]}
        except EngineError as exc:
            raise HTTPException(status_code=422, detail=[_error_payload(exc)]) from exc
        return {
            "outputs": {nid: {s: to_jsonable(v) for s, v in sockets.items()}
                        for nid, sockets in result.outputs.items()},
            "order": result.order,
            "output": graph.output,
            "errors": [],
        }

    @app.post("/api/export")
    def export(body: dict = Body(...)) -> dict:
        try:
            return {"python": to_python(_graph_from(body), registry)}
        except EngineError as exc:
            raise HTTPException(status_code=422, detail=[_error_payload(exc)]) from exc

    @app.get("/api/source/{spec_id}")
    def get_source(spec_id: str) -> JSONResponse:
        return JSONResponse(status_code=501, content={"message": "source editing is not implemented yet (stream E)"})

    @app.put("/api/source/{spec_id}")
    def put_source(spec_id: str, body: dict = Body(default={})) -> JSONResponse:
        return JSONResponse(status_code=501, content={"message": "source editing is not implemented yet (stream E)"})

    # Serve the built SPA at "/" — mounted LAST so /api/* routes win. Skipped
    # gracefully when the bundle hasn't been built (opening "/" would 404).
    if web_dist is not None and web_dist.is_dir():
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")

    return app
