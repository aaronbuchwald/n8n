"""FastAPI application wiring the engine to HTTP (see package docstring)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger("server")

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
from .workspace import SourceEditError, Workspace, find_repo_root, git_branch_info


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
    workspace: Optional[Workspace] = None,
) -> FastAPI:
    """Build the app over ``registry`` (defaults to the process registry).

    ``sample_graph`` — an engine ``Graph`` or its JSON dict — is served by
    ``GET /api/graph`` so a client has something to render. Its node ``type``s
    must all exist in ``registry`` (``GET /api/specs``). ``None`` → the endpoint
    replies 404.

    ``workspace`` — a :class:`~server.workspace.Workspace` binding the app to a
    real authoring module on disk. With it, source editing goes live:
    ``GET/PUT /api/source/{spec_id}`` read/write the actual ``@node`` function
    in the ``.py`` file, and ``PUT /api/graph`` rewrites the ``@main``
    composite's wiring lines (ADR 0004 D2/D5). Without it those routes keep
    replying 501, as before.

    ``web_dist`` — if the directory exists, the built web app is mounted at
    ``/`` (``html=True``) so the SPA is served **same-origin** with ``/api/*``
    (the web already fetches relative ``/api/*``). It is mounted **last** so it
    never shadows an ``/api`` route. Pass ``None`` (or point at a missing dir)
    to skip the mount — e.g. when the web is served separately via ``pnpm dev``.
    """
    registry = registry or DEFAULT_REGISTRY
    # Normalise to the engine graph JSON dict once; accept a Graph or a dict.
    # Kept in a one-slot dict so PUT /api/graph can swap in the saved graph.
    state: dict[str, Optional[dict]] = {
        "graph": sample_graph.to_dict() if isinstance(sample_graph, Graph) else sample_graph
    }
    app = FastAPI(title="graph-engine", version=SCHEMA_VERSION)

    @app.get("/api/specs")
    def get_specs() -> dict:
        return {"version": SCHEMA_VERSION, "specs": registry.specs()}

    @app.get("/api/graph")
    def get_graph() -> JSONResponse:
        if state["graph"] is None:
            return JSONResponse(status_code=404, content={"message": "no sample graph is configured"})
        return JSONResponse(status_code=200, content=state["graph"])

    @app.get("/api/workspace")
    def get_workspace() -> dict:
        if workspace is not None:
            return workspace.info()
        # No editable module bound — still report the branch this server runs from.
        return {**git_branch_info(find_repo_root(Path(__file__).resolve().parent)), "modules": []}

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

    def _no_workspace() -> JSONResponse:
        return JSONResponse(
            status_code=501,
            content={"message": "source editing requires a workspace (start with --demo or pass workspace=)"},
        )

    def _rebind_current_graph() -> list[dict]:
        """Re-validate the served graph after a source edit; report, don't fail.

        An edit can legitimately break the wiring (e.g. renaming a parameter
        the graph feeds) — the file write already happened, so surface the bind
        errors for the UI instead of pretending the save failed.
        """
        if state["graph"] is None:
            return []
        try:
            bind(Graph.from_dict(state["graph"]), registry)
        except EngineError as exc:
            return [_error_payload(exc)]
        return []

    @app.get("/api/source/{spec_id}")
    def get_source(spec_id: str) -> JSONResponse:
        if workspace is None:
            return _no_workspace()
        try:
            return JSONResponse(status_code=200, content=workspace.function_source(spec_id))
        except SourceEditError as exc:
            return JSONResponse(status_code=exc.status, content={"message": str(exc)})

    @app.put("/api/source/{spec_id}")
    def put_source(spec_id: str, body: dict = Body(default={})) -> JSONResponse:
        if workspace is None:
            return _no_workspace()
        source = body.get("source")
        if not isinstance(source, str) or not source.strip():
            return JSONResponse(status_code=400, content={"message": "body must be {\"source\": \"<function definition>\"}"})
        try:
            result = workspace.replace_function_source(spec_id, source)
        except SourceEditError as exc:
            return JSONResponse(status_code=exc.status, content={"message": str(exc)})
        result["spec"] = registry.spec(spec_id)  # re-introspected after reload
        result["graphErrors"] = _rebind_current_graph()
        return JSONResponse(status_code=200, content=result)

    @app.put("/api/graph")
    def put_graph(body: dict = Body(...)) -> JSONResponse:
        if workspace is None:
            return _no_workspace()
        try:
            graph = _graph_from(body)
            saved = workspace.save_graph(graph)  # writes wiring + sidecar, reloads
        except SourceEditError as exc:
            return JSONResponse(status_code=exc.status, content={"message": str(exc)})
        except EngineError as exc:
            raise HTTPException(status_code=422, detail=[_error_payload(exc)]) from exc
        state["graph"] = saved
        return JSONResponse(status_code=200, content={"graph": saved})

    # Serve the built SPA at "/" — mounted LAST so /api/* routes win. When the
    # bundle isn't built we mount nothing: the API stays live and "/" simply
    # 404s. Log which case we're in so the startup output is clear.
    if web_dist is not None and web_dist.is_dir():
        logger.info("web/dist found at %s — app served at /", web_dist)
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")
    else:
        logger.warning("web/dist not built — serving API only; run: cd web && pnpm build")

    return app
