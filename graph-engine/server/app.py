"""FastAPI application wiring the engine to HTTP (see package docstring)."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import JSONResponse

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
    """Structured error; carries a nodeId when the exception exposes one."""
    node_id = getattr(exc, "node_id", None)
    payload: dict[str, Any] = {"code": type(exc).__name__, "message": str(exc)}
    if node_id is not None:
        payload["nodeId"] = node_id
    return payload


def _graph_from(body: dict) -> Graph:
    """Accept either ``{"graph": {...}}`` or a bare graph object."""
    raw = body.get("graph", body) if isinstance(body, dict) else body
    validate_graph(raw)  # shape + referential integrity (raises SchemaError)
    return Graph.from_dict(raw)


def create_app(registry: Optional[NodeRegistry] = None) -> FastAPI:
    """Build the app over ``registry`` (defaults to the process registry)."""
    registry = registry or DEFAULT_REGISTRY
    app = FastAPI(title="graph-engine", version=SCHEMA_VERSION)

    @app.get("/api/specs")
    def get_specs() -> dict:
        return {"version": SCHEMA_VERSION, "specs": registry.specs()}

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

    return app
