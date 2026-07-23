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
    UnknownNodeType,
    bind,
    mint_node_id,
    module_collision_set,
    run,
    to_python,
    validate_graph,
)

from .entries import EntryCatalog, EntryLoadError, UnknownEntryError
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

    ``message`` prefers the exception's own ``message`` attribute when it has
    one (``NodeExecutionError`` sets it to the raw cause text, no node-id
    prefix) over ``str(exc)``, so a UI reading ``{nodeId, message}`` never has
    to strip a baked-in prefix itself (review 0005 #14).
    """
    message = getattr(exc, "message", None)
    payload: dict[str, Any] = {"code": type(exc).__name__, "message": message if message is not None else str(exc)}
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


def _resolve_run_paths(graph: Graph, base_dir: Optional[Path]) -> Graph:
    """A copy of ``graph`` with relative ``path`` inputs resolved against ``base_dir``.

    Applied **only** to the graph handed to :func:`engine.run` inside
    ``/api/run`` — never to what ``GET /api/graph`` serves or what
    ``PUT /api/graph`` persists, which both keep the literal exactly as authored
    (review 0005 #3). This is the modular replacement for per-example path lists:
    any node input named ``path`` that is a *relative* string is resolved against
    the served program's own directory, so a program with N CSV reads (each a
    different relative file) runs from any working directory, unchanged, with no
    absolute path ever reaching the source.
    """
    if base_dir is None:
        return graph
    patched = Graph.from_dict(graph.to_dict())  # deep copy; never mutate the caller's graph
    for node in patched.nodes:
        value = node.inputs.get("path")
        if isinstance(value, str) and value and not Path(value).is_absolute():
            node.inputs["path"] = str(base_dir / value)
    return patched


def create_app(
    registry: Optional[NodeRegistry] = None,
    sample_graph: Optional[Any] = None,
    web_dist: Optional[Path] = WEB_DIST,
    workspace: Optional[Workspace] = None,
    run_base_dir: Optional[Path] = None,
    catalog: Optional[EntryCatalog] = None,
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

    ``run_base_dir`` — the served program's directory; relative ``path`` inputs
    are resolved against it **only** while executing ``/api/run``, so a program
    can run from any working directory without the absolute path ever reaching
    the served graph, a widget commit, or ``PUT /api/graph`` (review 0005 #3;
    see ``server/demo.py``). Modular: works for any number of file reads.

    ``web_dist`` — if the directory exists, the built web app is mounted at
    ``/`` (``html=True``) so the SPA is served **same-origin** with ``/api/*``
    (the web already fetches relative ``/api/*``). It is mounted **last** so it
    never shadows an ``/api`` route. Pass ``None`` (or point at a missing dir)
    to skip the mount — e.g. when the web is served separately via ``pnpm dev``.

    ``catalog`` — an :class:`~server.entries.EntryCatalog` of viewable entry
    points (ADR 0009). With it, ``GET /api/graphs`` lists every entry and the
    id-scoped routes (``/api/graphs/{id}/graph`` …) serve each entry through
    its own memoized workspace. The **unscoped** routes then become aliases for
    the catalog's *default* entry (one migration wave); without a catalog they
    keep the single-slot behavior driven by ``sample_graph``/``workspace``.
    Selection is a client concern — the server holds no "active entry".
    """
    registry = registry or DEFAULT_REGISTRY
    # Normalise to the engine graph JSON dict once; accept a Graph or a dict.
    # Kept in a one-slot dict so PUT /api/graph can swap in the saved graph.
    state: dict[str, Optional[dict]] = {
        "graph": sample_graph.to_dict() if isinstance(sample_graph, Graph) else sample_graph
    }
    app = FastAPI(title="graph-engine", version=SCHEMA_VERSION)

    # -- entry resolution (ADR 0009 D4) ---------------------------------
    # Scoped routes resolve `(workspace, run_base_dir)` through the catalog's
    # memoized pool. The unscoped routes stay as aliases for the *default*
    # entry when a catalog exists; otherwise they keep the legacy single-slot
    # closure (`sample_graph` + `workspace`) so existing embedders/tests work.

    def _entry_slot(entry_id: str) -> tuple[Workspace, Path]:
        if catalog is None:
            raise HTTPException(status_code=404, detail="no entry catalog is configured")
        try:
            return catalog.workspace(entry_id)
        except UnknownEntryError as exc:
            raise HTTPException(status_code=404, detail=exc.message) from exc
        except EntryLoadError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def _default_slot() -> Optional[tuple[Workspace, Path]]:
        """The default entry's slot, or None when running without a catalog."""
        if catalog is None or catalog.default is None:
            return None
        return _entry_slot(catalog.default)

    def _serve_entry_graph(ws: Workspace) -> JSONResponse:
        # Reparse from disk on every read — with several coexisting views over
        # one branch this is the read half of the last-write-wins-with-reparse
        # concurrency strategy (ADR 0009, "Concurrency strategy").
        try:
            return JSONResponse(status_code=200, content=ws.parse_graph())
        except SourceEditError as exc:
            return JSONResponse(status_code=exc.status, content={"message": str(exc)})
        except EngineError as exc:
            # Imported fine but no longer projects to a graph (e.g. two @main
            # defs): the listing reports it as status:"error"; direct access 409s.
            return JSONResponse(status_code=409, content={"message": str(exc)})

    def _run_impl(body: dict, base_dir: Optional[Path]) -> dict:
        try:
            graph = _graph_from(body)
        except EngineError as exc:
            raise HTTPException(status_code=422, detail=[_error_payload(exc)]) from exc
        try:
            # environment honoured by stream C later; path resolution never
            # touches `graph` itself, only the copy handed to the executor.
            result = run(_resolve_run_paths(graph, base_dir), registry)
        except NodeExecutionError as exc:
            # ADR 0002's shape is additive on failure: `errors` is unchanged,
            # but `outputs`/`order` now carry every node that ran before the
            # failure instead of being discarded (review 0005 #6).
            return {
                "outputs": {nid: {s: to_jsonable(v) for s, v in sockets.items()}
                            for nid, sockets in exc.outputs.items()},
                "order": exc.order,
                "output": graph.output,
                "errors": [_error_payload(exc)],
            }
        except EngineError as exc:
            raise HTTPException(status_code=422, detail=[_error_payload(exc)]) from exc
        return {
            "outputs": {nid: {s: to_jsonable(v) for s, v in sockets.items()}
                        for nid, sockets in result.outputs.items()},
            "order": result.order,
            "output": graph.output,
            "errors": [],
        }

    @app.get("/api/specs")
    def get_specs() -> dict:
        return {"version": SCHEMA_VERSION, "specs": registry.specs()}

    @app.post("/api/specs/{spec_id}/derive")
    def derive_inputs(spec_id: str, body: dict = Body(...)) -> JSONResponse:
        """Derive a dynamic node's input sockets from a value (ADR 0007 D4).

        Python-authoritative: the UI posts the draft equation and gets back the
        socket list the engine would derive at bind time — one implementation, no
        JS parser. Stateless and registry-only (no workspace needed).

        * ``200 -> {"inputs": [...derived entries...]}``
        * ``422 -> {"errors": [{"code","message"}]}`` — the value is invalid.
        * ``404`` — the spec is unknown or not dynamic.
        """
        try:
            entry = registry.get(spec_id)
        except UnknownNodeType:
            return JSONResponse(status_code=404, content={"message": f"spec {spec_id!r} is not registered"})
        if entry.dynamic is None:
            return JSONResponse(status_code=404, content={"message": f"spec {spec_id!r} has no derived inputs"})
        value = body.get("value") if isinstance(body, dict) else body
        try:
            inputs = entry.dynamic.derive(value)
        except EngineError as exc:
            return JSONResponse(status_code=422, content={"errors": [_error_payload(exc)]})
        return JSONResponse(status_code=200, content={"inputs": inputs})

    @app.get("/api/graphs")
    def list_graphs() -> dict:
        """Every viewable entry point + the advisory default (ADR 0009 D4)."""
        if catalog is None:
            return {"version": SCHEMA_VERSION, "default": None, "entries": []}
        return {
            "version": SCHEMA_VERSION,
            "default": catalog.default,
            "entries": catalog.entries(),
        }

    @app.get("/api/graphs/{entry_id}/graph")
    def get_entry_graph(entry_id: str) -> JSONResponse:
        ws, _ = _entry_slot(entry_id)
        return _serve_entry_graph(ws)

    @app.post("/api/graphs/{entry_id}/run")
    def run_entry_graph(entry_id: str, body: dict = Body(...)) -> dict:
        _, base_dir = _entry_slot(entry_id)
        return _run_impl(body, base_dir)

    @app.get("/api/graph")
    def get_graph() -> JSONResponse:
        slot = _default_slot()
        if slot is not None:  # unscoped alias for the default entry (one wave)
            return _serve_entry_graph(slot[0])
        if state["graph"] is None:
            return JSONResponse(status_code=404, content={"message": "no sample graph is configured"})
        return JSONResponse(status_code=200, content=state["graph"])

    @app.get("/api/workspace")
    def get_workspace() -> dict:
        if catalog is not None:
            # The branch is checkout-global; `modules` grows to every viewable
            # entry's module (additive shape change, ADR 0009 D4).
            modules = [
                {"module": e["id"], "path": e["path"]}
                for e in catalog.entries()
                if e["status"] == "ok" and e["path"]
            ]
            return {
                **git_branch_info(find_repo_root(Path(__file__).resolve().parent)),
                "modules": modules,
            }
        if workspace is not None:
            return workspace.info()
        # No editable module bound — still report the branch this server runs from.
        return {**git_branch_info(find_repo_root(Path(__file__).resolve().parent)), "modules": []}

    @app.post("/api/graphs/validate")
    def validate(body: dict = Body(...)) -> JSONResponse:
        """Validate a candidate graph (ADR 0011 D6).

        ``mode`` (body field, default ``"run"``, backward-compatible): ``"run"``
        runs a full ``bind`` — a required input left unwired/unset is a hard
        error, unchanged. ``"edit"`` runs ``bind(partial=True)``: the same
        unsatisfied-required-input case is instead collected into a ``warnings``
        array on a 200 response, so an in-progress canvas draft validates (and
        can be saved) while genuinely broken wiring (unknown type/socket/param,
        double-wire, cycle, bad output) still 422s in both modes.
        """
        mode = body.get("mode", "run") if isinstance(body, dict) else "run"
        try:
            graph = _graph_from(body)
        except EngineError as exc:
            return JSONResponse(status_code=422, content={"ok": False, "errors": [_error_payload(exc)]})
        if mode == "edit":
            try:
                bound = bind(graph, registry, partial=True)
            except EngineError as exc:
                return JSONResponse(status_code=422, content={"ok": False, "errors": [_error_payload(exc)]})
            return JSONResponse(status_code=200, content={"ok": True, "warnings": bound.incomplete})
        try:
            bind(graph, registry)
        except EngineError as exc:
            return JSONResponse(status_code=422, content={"ok": False, "errors": [_error_payload(exc)]})
        return JSONResponse(status_code=200, content={"ok": True})

    @app.post("/api/run")
    def run_graph(body: dict = Body(...)) -> dict:
        slot = _default_slot()
        base_dir = slot[1] if slot is not None else run_base_dir
        return _run_impl(body, base_dir)

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

    def _rebind_graph_doc(doc: Optional[dict]) -> list[dict]:
        """Re-validate a served graph after a source edit; report, don't fail.

        An edit can legitimately break the wiring (e.g. renaming a parameter
        the graph feeds) — the file write already happened, so surface the bind
        errors for the UI instead of pretending the save failed.
        """
        if doc is None:
            return []
        try:
            bind(Graph.from_dict(doc), registry)
        except EngineError as exc:
            return [_error_payload(exc)]
        return []

    def _get_source_impl(ws: Workspace, spec_id: str) -> JSONResponse:
        try:
            return JSONResponse(status_code=200, content=ws.function_source(spec_id))
        except SourceEditError as exc:
            return JSONResponse(status_code=exc.status, content={"message": str(exc)})

    def _put_source_impl(ws: Workspace, spec_id: str, body: dict, current_doc) -> JSONResponse:
        """``current_doc`` lazily supplies the graph to re-bind after the write."""
        source = body.get("source")
        if not isinstance(source, str) or not source.strip():
            return JSONResponse(status_code=400, content={"message": "body must be {\"source\": \"<function definition>\"}"})
        try:
            result = ws.replace_function_source(spec_id, source)
        except SourceEditError as exc:
            return JSONResponse(status_code=exc.status, content={"message": str(exc)})
        result["spec"] = registry.spec(spec_id)  # re-introspected after reload
        # A code edit reparses to the graph (ADR 0004 D2): return the fresh
        # projection beside `spec` so the client invalidates run-derived views
        # instead of reading a boot-time cache (ADR 0008 G3; "writes return
        # truth", mirroring PUT /api/graph → {graph}). `current_doc` reparses the
        # edited workspace — per-entry under a catalog, the single slot in the
        # legacy path — so it is fresh and correct for both.
        doc = current_doc()
        result["graph"] = doc
        result["graphErrors"] = _rebind_graph_doc(doc)
        return JSONResponse(status_code=200, content=result)

    def _post_source_impl(ws: Workspace, body: dict, current_doc) -> JSONResponse:
        """``POST .../source`` — author a brand-new ``@node`` (ADR 0011 D7).

        Body: ``{"source": "<@node function>", "module": "<target>"?}``.
        ``module`` is optional and defaults to the workspace's own module (HD1);
        when present it must be one of ``list_target_modules()``'s entries — an
        already-imported module inside ``allowed_roots`` — which
        ``create_function`` itself enforces, so the picker and the write can
        never disagree about what's a legal destination. The response mirrors a
        source edit's shape (path/line-range/source + re-introspected `spec` +
        the re-projected `graph`), so the same client-side ingest path
        (``ingestSourceSave``) that handles PUT /api/source handles this too —
        the new type appears in the palette on the very next specs read.
        """
        source = body.get("source") if isinstance(body, dict) else None
        if not isinstance(source, str) or not source.strip():
            return JSONResponse(status_code=400, content={"message": "body must be {\"source\": \"<function definition>\"}"})
        module = body.get("module") if isinstance(body, dict) else None
        if module is not None and not isinstance(module, str):
            return JSONResponse(status_code=400, content={"message": "\"module\" must be a string when present"})
        try:
            result = ws.create_function(source, module=module or None)
        except SourceEditError as exc:
            return JSONResponse(status_code=exc.status, content={"message": str(exc)})
        spec_id = f"{result['module']}.{result['qualname']}"
        result["spec"] = registry.spec(spec_id)  # re-introspected after reload
        doc = current_doc()
        result["graph"] = doc
        result["graphErrors"] = _rebind_graph_doc(doc)
        return JSONResponse(status_code=200, content=result)

    def _put_graph_impl(ws: Workspace, body: dict) -> JSONResponse:
        try:
            graph = _graph_from(body)
            saved = ws.save_graph(graph)  # writes wiring + sidecar, reloads
        except SourceEditError as exc:
            return JSONResponse(status_code=exc.status, content={"message": str(exc)})
        except EngineError as exc:
            raise HTTPException(status_code=422, detail=[_error_payload(exc)]) from exc
        # W2->W3 seam: `save_graph` parks a structural-fallback warning at
        # `graph["writeback"]` (server/workspace.py) because the lossy path is
        # the only one that needs to say anything beyond the projection itself.
        # Lift it onto the envelope as a top-level field instead of leaving it on
        # `graph`, so a lossless save's `graph` is byte-for-byte what GET serves
        # (`GET == PUT` holds even when a warning rides alongside it).
        warning = saved.pop("writeback", None)
        state["graph"] = saved
        envelope: dict[str, Any] = {"graph": saved}
        if warning is not None:
            envelope["writeback"] = warning
        return JSONResponse(status_code=200, content=envelope)

    def _mint_id_impl(ws: Workspace, body: dict) -> JSONResponse:
        """``POST .../mint-id {"type": "<spec id>"} -> {"id": "<node id>"}`` (HD4).

        Server-assisted because the collision set that must be dodged lives in
        the *module* (its call names, the composite's own parameter names, and
        builtins it references) — data the client doesn't have. Re-checked at
        save time (``save_graph`` -> ``wiring_lines``) as a backstop, so a stale
        mint (e.g. a concurrent save) still fails loudly rather than silently
        shadowing something.
        """
        node_type = body.get("type") if isinstance(body, dict) else None
        if not isinstance(node_type, str) or not node_type:
            return JSONResponse(
                status_code=400,
                content={"message": "body must be {\"type\": \"<registered spec id>\"}"},
            )
        try:
            spec = registry.spec(node_type)
        except UnknownNodeType:
            return JSONResponse(
                status_code=404, content={"message": f"spec {node_type!r} is not registered"}
            )
        try:
            source = ws.module_file().read_text(encoding="utf-8")
            doc = ws.parse_graph()
        except SourceEditError as exc:
            return JSONResponse(status_code=exc.status, content={"message": str(exc)})
        except EngineError as exc:
            # Imported fine but no longer projects to a graph (e.g. two @main
            # defs) — nothing sane to mint against.
            return JSONResponse(status_code=409, content={"message": str(exc)})
        node_ids = [n["id"] for n in doc["nodes"]]
        # A type from another module isn't imported yet, so its future call name
        # (the plain qualname write-back would import it under; see
        # server/writeback.py's `_aliases`) isn't in the source's collision set
        # yet — reserve it so the minted id never shadows its own import.
        extra = () if spec["module"] == ws.module_name else (spec["qualname"],)
        try:
            collisions = module_collision_set(
                source, ws.module_name, node_ids=node_ids, extra=extra
            )
        except EngineError as exc:
            return JSONResponse(status_code=409, content={"message": str(exc)})
        minted = mint_node_id(spec["name"], collisions)
        return JSONResponse(status_code=200, content={"id": minted})

    def _entry_doc(ws: Workspace):
        """A lazy graph-doc getter for `_put_source_impl` (reparse, never cache)."""
        def get() -> Optional[dict]:
            try:
                return ws.parse_graph()
            except Exception:  # the graph may no longer project; nothing to rebind
                return None
        return get

    @app.get("/api/graphs/{entry_id}/source/{spec_id}")
    def get_entry_source(entry_id: str, spec_id: str) -> JSONResponse:
        ws, _ = _entry_slot(entry_id)
        return _get_source_impl(ws, spec_id)

    @app.put("/api/graphs/{entry_id}/source/{spec_id}")
    def put_entry_source(entry_id: str, spec_id: str, body: dict = Body(default={})) -> JSONResponse:
        ws, _ = _entry_slot(entry_id)
        return _put_source_impl(ws, spec_id, body, _entry_doc(ws))

    @app.post("/api/graphs/{entry_id}/source")
    def post_entry_source(entry_id: str, body: dict = Body(default={})) -> JSONResponse:
        ws, _ = _entry_slot(entry_id)
        return _post_source_impl(ws, body, _entry_doc(ws))

    @app.get("/api/graphs/{entry_id}/source-targets")
    def get_entry_source_targets(entry_id: str) -> JSONResponse:
        ws, _ = _entry_slot(entry_id)
        return JSONResponse(status_code=200, content={"targets": ws.list_target_modules()})

    @app.put("/api/graphs/{entry_id}/graph")
    def put_entry_graph(entry_id: str, body: dict = Body(...)) -> JSONResponse:
        ws, _ = _entry_slot(entry_id)
        return _put_graph_impl(ws, body)

    @app.post("/api/graphs/{entry_id}/mint-id")
    def mint_entry_node_id(entry_id: str, body: dict = Body(...)) -> JSONResponse:
        ws, _ = _entry_slot(entry_id)
        return _mint_id_impl(ws, body)

    @app.get("/api/source/{spec_id}")
    def get_source(spec_id: str) -> JSONResponse:
        slot = _default_slot()
        ws = slot[0] if slot is not None else workspace
        if ws is None:
            return _no_workspace()
        return _get_source_impl(ws, spec_id)

    @app.put("/api/source/{spec_id}")
    def put_source(spec_id: str, body: dict = Body(default={})) -> JSONResponse:
        slot = _default_slot()
        if slot is not None:
            return _put_source_impl(slot[0], spec_id, body, _entry_doc(slot[0]))
        if workspace is None:
            return _no_workspace()

        def _legacy_doc() -> Optional[dict]:
            # Legacy single-slot: reparse the edited module and refresh the slot
            # so GET /api/graph also reflects the edit (ADR 0008 G3).
            state["graph"] = workspace.parse_graph()
            return state["graph"]

        return _put_source_impl(workspace, spec_id, body, _legacy_doc)

    @app.post("/api/source")
    def post_source(body: dict = Body(default={})) -> JSONResponse:
        slot = _default_slot()
        if slot is not None:
            return _post_source_impl(slot[0], body, _entry_doc(slot[0]))
        if workspace is None:
            return _no_workspace()

        def _legacy_doc() -> Optional[dict]:
            # Legacy single-slot: reparse the edited module and refresh the slot
            # so GET /api/graph also reflects the new function (ADR 0008 G3).
            state["graph"] = workspace.parse_graph()
            return state["graph"]

        return _post_source_impl(workspace, body, _legacy_doc)

    @app.get("/api/source-targets")
    def get_source_targets() -> JSONResponse:
        slot = _default_slot()
        ws = slot[0] if slot is not None else workspace
        if ws is None:
            return _no_workspace()
        return JSONResponse(status_code=200, content={"targets": ws.list_target_modules()})

    @app.put("/api/graph")
    def put_graph(body: dict = Body(...)) -> JSONResponse:
        slot = _default_slot()
        ws = slot[0] if slot is not None else workspace
        if ws is None:
            return _no_workspace()
        return _put_graph_impl(ws, body)

    @app.post("/api/graph/mint-id")
    def mint_node_id_route(body: dict = Body(...)) -> JSONResponse:
        slot = _default_slot()
        ws = slot[0] if slot is not None else workspace
        if ws is None:
            return _no_workspace()
        return _mint_id_impl(ws, body)

    # Serve the built SPA at "/" — mounted LAST so /api/* routes win. When the
    # bundle isn't built we mount nothing: the API stays live and "/" simply
    # 404s. Log which case we're in so the startup output is clear.
    if web_dist is not None and web_dist.is_dir():
        logger.info("web/dist found at %s — app served at /", web_dist)
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")
    else:
        logger.warning("web/dist not built — serving API only; run: cd web && pnpm build")

    return app
