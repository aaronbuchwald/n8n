"""``to_composite`` / ``from_composite`` — the Graph ⟷ authoring-module bijection.

ADR 0004 fixes the bijective surface as **Graph ⟷ wiring composite**: a
``@main`` function whose body is a straight-line sequence of single-assignment
calls (``v = fn(args)``). The composite's local **variable name is the node id**
(ADR 0004 D3); an argument that references another variable is an **edge**; a
literal argument is a **widget value**. This module is the parse ↔ emit pair over
that composite text — distinct from :mod:`engine.emit`, whose ``to_python`` is a
*derived flat script*, not the round-trip surface (ADR 0004 D1/D4).

* :func:`to_composite` — Graph → authoring-module source (the emit direction).
* :func:`from_composite` — authoring-module source → Graph (the AST-parse
  inverse). Control flow is rejected: composites are dataflow only (ADR 0004 D7).

The round-trip is an identity **modulo layout** (positions live in a sidecar,
ADR 0004 D6) **and wiring-line formatting** (normalized on emit).
"""

from __future__ import annotations

import ast
from typing import Optional

from .bind import BoundGraph, BoundNode, bind
from .errors import EngineError
from .graph import Graph
from .registry import DEFAULT_REGISTRY, NodeRegistry
from .spec import DEFAULT_OUTPUT, is_multi_output

__all__ = ["to_composite", "from_composite", "wiring_lines", "find_composite"]


# ======================================================================
# Graph -> composite source (emit)
# ======================================================================


def _aliases(bound: BoundGraph) -> tuple[dict[str, str], list[str]]:
    """Assign each used node type a call-name alias and build the import lines.

    Node ids are *variable names* in the composite body, so a call name that
    equals any node id would be shadowed by that local variable
    (``total = total(vals)`` reads the unbound local, not the function). The
    reserved set therefore includes every node id — the collision-avoidance idea
    from :mod:`engine.emit`, extended to also dodge the variable names.
    """
    used: dict[str, dict] = {}
    for node in bound.nodes:
        used.setdefault(node.type, node.spec)

    # Every node id is a live local in the body — an alias must never collide.
    taken: set[str] = {node.id for node in bound.nodes}
    alias_of: dict[str, str] = {}
    imports: list[str] = []
    for type_id, spec in used.items():
        base = spec["qualname"]
        alias, n = base, 1
        while alias in taken:
            n += 1
            alias = f"{base}_{n}"
        taken.add(alias)
        alias_of[type_id] = alias
        suffix = "" if alias == base else f" as {alias}"
        imports.append(f"from {spec['module']} import {base}{suffix}")
    return alias_of, imports


def _ref(source: BoundNode, socket: str) -> str:
    """The RHS expression referencing an upstream node's output.

    A single-output source is referenced by its bare variable (socket implied);
    a multi-output source is subscripted with the chosen socket name.
    """
    if is_multi_output(source.spec):
        return f"{source.id}[{socket!r}]"
    return source.id


def _render_value(bound: BoundNode, param: str) -> str:
    if param in bound.wired:
        source, socket = bound.wired[param]
        return _ref(source, socket)
    return repr(bound.literals[param])


def _arg_exprs(bound: BoundNode) -> str:
    """Render a node's call arguments, honouring parameter kinds (mirrors emit).

    Positional-only params are emitted positionally (a contiguous prefix, gaps
    filled with their defaults); every other provided input is emitted as
    ``name=value``.
    """
    inputs = bound.spec["inputs"]
    provided = set(bound.wired) | set(bound.literals)
    parts: list[str] = []

    pos_only = [i for i in inputs if i["kind"] == "positionalOnly"]
    if pos_only:
        supplied = [k for k, i in enumerate(pos_only) if i["name"] in provided]
        last = max(supplied) if supplied else -1
        for k in range(last + 1):
            inp = pos_only[k]
            if inp["name"] in provided:
                parts.append(_render_value(bound, inp["name"]))
            else:
                parts.append(inp.get("defaultRepr") or repr(inp["default"]))

    for inp in inputs:
        if inp["kind"] == "positionalOnly":
            continue
        if inp["name"] in provided:
            parts.append(f"{inp['name']}={_render_value(bound, inp['name'])}")
    return ", ".join(parts)


def to_composite(
    graph: Graph,
    registry: Optional[NodeRegistry] = None,
    *,
    name: str = "main_graph",
) -> str:
    """Emit a runnable authoring-module source string for ``graph``.

    The result is a ``@main`` composite whose body is one single-assignment call
    per node (in topological order), with the node id as the assignment
    variable. Imports are aliased so a call name never collides with a node-id
    variable. Re-parsing the result with :func:`from_composite` reconstructs the
    graph (modulo layout / wiring-line formatting; ADR 0004).
    """
    bound = graph if isinstance(graph, BoundGraph) else bind(graph, registry)

    alias_of, type_imports = _aliases(bound)
    body = [f"    {n.id} = {alias_of[n.type]}({_arg_exprs(n)})" for n in bound.nodes]

    return_line = ""
    if bound.output is not None:
        onode, osocket = bound.output
        return_line = f"    return {_ref(onode, osocket)}"

    lines: list[str] = ["from engine import main"]
    lines += type_imports
    lines += ["", "", "@main", f"def {name}():"]
    if body or return_line:
        lines += body
        if return_line:
            lines.append(return_line)
    else:
        lines.append("    pass")
    return "\n".join(lines) + "\n"


def wiring_lines(
    graph: Graph,
    registry: Optional[NodeRegistry] = None,
    *,
    module: Optional[str] = None,
    indent: str = "    ",
) -> list[str]:
    """Emit only the composite-body wiring lines (assignments + ``return``).

    Used when patching a composite **in place** inside its own authoring module
    (ADR 0004 D5): the ``@node`` functions are defined in that same module, so
    calls are emitted by bare qualname and no imports are added. ``module``
    (when given) asserts every node type is defined there. Because a node id is
    a local variable of the composite, an id equal to a called function name
    would shadow that function (Python function-scoping) — rejected with a
    rename hint rather than emitting broken code.
    """
    bound = graph if isinstance(graph, BoundGraph) else bind(graph, registry)

    if module is not None:
        for n in bound.nodes:
            if n.spec["module"] != module:
                raise EngineError(
                    f"node {n.id!r} has type {n.type!r} from module "
                    f"{n.spec['module']!r}; in-place wiring can only call "
                    f"functions defined in {module!r}"
                )

    node_ids = {n.id for n in bound.nodes}
    call_of: dict[str, str] = {}
    for n in bound.nodes:
        qualname = n.spec["qualname"]
        if qualname in node_ids:
            raise EngineError(
                f"a node is named {qualname!r}, which shadows the function it "
                f"must call — rename that node (node id = variable name, "
                f"ADR 0004 D3)"
            )
        call_of[n.type] = qualname

    lines = [f"{indent}{n.id} = {call_of[n.type]}({_arg_exprs(n)})" for n in bound.nodes]
    if bound.output is not None:
        onode, osocket = bound.output
        lines.append(f"{indent}return {_ref(onode, osocket)}")
    return lines or [f"{indent}pass"]


# ======================================================================
# composite source -> Graph (AST parse, the inverse)
# ======================================================================

# Import module we deliberately ignore — it carries the decorators, not a type.
_ENGINE_MODULE = "engine"
_COMPOSITE_DECORATORS = {"main", "graph"}


def _import_map(tree: ast.Module) -> dict[str, str]:
    """Map each imported local name to a ``module.qualname`` registry id.

    Handles ``from X import Y`` and ``from X import Y as Z``. ``from engine
    import ...`` (the decorators) is skipped — it names no node type.
    """
    mapping: dict[str, str] = {}
    for stmt in tree.body:
        if not isinstance(stmt, ast.ImportFrom) or stmt.module is None:
            continue
        if stmt.module == _ENGINE_MODULE:
            continue
        for alias in stmt.names:
            local = alias.asname or alias.name
            mapping[local] = f"{stmt.module}.{alias.name}"
    return mapping


def find_composite(tree: ast.Module) -> ast.FunctionDef:
    """Locate the composite: the ``@main``/``@graph`` def, else the lone def."""
    functions = [s for s in tree.body if isinstance(s, ast.FunctionDef)]

    def _is_composite(fn: ast.FunctionDef) -> bool:
        for dec in fn.decorator_list:
            target = dec.func if isinstance(dec, ast.Call) else dec
            if isinstance(target, ast.Name) and target.id in _COMPOSITE_DECORATORS:
                return True
            if isinstance(target, ast.Attribute) and target.attr in _COMPOSITE_DECORATORS:
                return True
        return False

    decorated = [fn for fn in functions if _is_composite(fn)]
    if len(decorated) == 1:
        return decorated[0]
    if not decorated and len(functions) == 1:
        return functions[0]
    if not functions:
        raise EngineError("no composite function found in the source")
    raise EngineError(
        "expected exactly one @main/@graph composite; found "
        f"{len(decorated) or len(functions)}"
    )


def _param_defaults(fn: ast.FunctionDef) -> dict[str, object]:
    """The composite's parameters that carry a *literal* default.

    A wiring argument that references such a parameter collapses to that
    default value as a widget literal — the parameter indirection itself is not
    graph-representable, so this is the closest faithful projection. Parameters
    with non-literal defaults are simply omitted (referencing one errors).
    """
    out: dict[str, object] = {}
    args = fn.args
    positional = args.posonlyargs + args.args
    for arg, default in zip(positional[len(positional) - len(args.defaults):], args.defaults):
        try:
            out[arg.arg] = ast.literal_eval(default)
        except (ValueError, SyntaxError):
            continue
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        if default is None:
            continue
        try:
            out[arg.arg] = ast.literal_eval(default)
        except (ValueError, SyntaxError):
            continue
    return out


def _socket_from_reference(value: ast.expr, node_ids: set[str]) -> Optional[tuple[str, str]]:
    """If ``value`` references a known node, return ``(node_id, socket)``.

    * bare ``Name`` (``x``)      → ``(x, "result")`` — the single output socket.
    * ``Subscript`` (``x["s"]``) → ``(x, "s")``.
    * ``Attribute`` (``x.s``)    → ``(x, "s")``.

    Returns ``None`` when ``value`` is not a reference to a known node id (the
    caller then treats it as a literal widget value).
    """
    if isinstance(value, ast.Name):
        return (value.id, DEFAULT_OUTPUT) if value.id in node_ids else None
    if isinstance(value, ast.Subscript) and isinstance(value.value, ast.Name):
        if value.value.id not in node_ids:
            return None
        index = value.slice
        if not (isinstance(index, ast.Constant) and isinstance(index.value, str)):
            raise EngineError(
                f"socket subscript on {value.value.id!r} must be a string literal"
            )
        return (value.value.id, index.value)
    if isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name):
        if value.value.id not in node_ids:
            return None
        return (value.value.id, value.attr)
    return None


def _literal_value(value: ast.expr, target: str, param: str, params: dict[str, object]):
    """Interpret ``value`` as a widget literal, or raise a clear error."""
    if isinstance(value, ast.Constant):
        return value.value
    if isinstance(value, ast.Name) and value.id in params:
        return params[value.id]  # composite parameter → its literal default
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        raise EngineError(
            f"argument for input {param!r} of node {target!r} is neither a "
            f"reference to an earlier node, a composite parameter with a "
            f"literal default, nor a literal value "
            f"(got {type(value).__name__}); composites are straight-line "
            f"dataflow (ADR 0004 D7)"
        ) from None


def _resolve_type(
    call: ast.Call, imports: dict[str, str], registry: NodeRegistry, target: str
) -> str:
    """Resolve a ``Call.func`` (a ``Name``) to a registered node-type id."""
    func = call.func
    if not isinstance(func, ast.Name):
        raise EngineError(
            f"node {target!r} must call a plain imported name, not "
            f"{type(func).__name__}"
        )
    type_id = imports.get(func.id)
    if type_id is None:
        raise EngineError(
            f"node {target!r} calls {func.id!r}, which is not an imported node type"
        )
    if type_id not in registry:
        raise EngineError(
            f"node {target!r} has unknown type {type_id!r} (not in the registry)"
        )
    return type_id


def _parse_assignment(
    stmt: ast.Assign,
    imports: dict[str, str],
    registry: NodeRegistry,
    graph: Graph,
    node_ids: set[str],
    pending_edges: list[tuple[str, str, str, str]],
    params: dict[str, object],
) -> None:
    """Turn a ``target = call(...)`` statement into a node (+ its edges)."""
    if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
        raise EngineError(
            "composite assignments must have a single Name target "
            "(no tuple/multi-target unpacking); composites are straight-line "
            "dataflow (ADR 0004 D7)"
        )
    target = stmt.targets[0].id
    if not isinstance(stmt.value, ast.Call):
        raise EngineError(
            f"node {target!r} must be assigned a single node call; "
            f"got {type(stmt.value).__name__} (ADR 0004 D7)"
        )

    call = stmt.value
    type_id = _resolve_type(call, imports, registry, target)
    input_names = [i["name"] for i in registry.spec(type_id)["inputs"]]

    # Map each argument to an input name: positionals by spec order, keywords by
    # their given name.
    named_args: list[tuple[str, ast.expr]] = []
    if len(call.args) > len(input_names):
        raise EngineError(
            f"node {target!r} ({type_id}) is called with {len(call.args)} "
            f"positional arguments but the type has {len(input_names)} inputs"
        )
    for pos, arg in enumerate(call.args):
        if isinstance(arg, ast.Starred):
            raise EngineError(
                f"node {target!r} uses argument unpacking (*args), which is not "
                f"representable as node wiring (ADR 0004 D7)"
            )
        named_args.append((input_names[pos], arg))
    for kw in call.keywords:
        if kw.arg is None:
            raise EngineError(
                f"node {target!r} uses **kwargs unpacking, which is not "
                f"representable as node wiring (ADR 0004 D7)"
            )
        named_args.append((kw.arg, kw.value))

    widgets: dict = {}
    for param, value in named_args:
        reference = _socket_from_reference(value, node_ids)
        if reference is not None:
            src_id, socket = reference
            pending_edges.append((src_id, socket, target, param))
        else:
            widgets[param] = _literal_value(value, target, param, params)

    graph.add(target, type_id, inputs=widgets)
    node_ids.add(target)


def _parse_return(stmt: ast.Return, graph: Graph, node_ids: set[str]) -> None:
    if stmt.value is None or (
        isinstance(stmt.value, ast.Constant) and stmt.value.value is None
    ):
        return  # `return` / `return None` → no graph output
    reference = _socket_from_reference(stmt.value, node_ids)
    if reference is None:
        raise EngineError(
            'composite return must reference a node (a variable, x["socket"], '
            "or x.socket)"
        )
    node_id, socket = reference
    graph.output = {"node": node_id, "socket": socket}


def from_composite(
    source: str,
    registry: Optional[NodeRegistry] = None,
    *,
    module_name: Optional[str] = None,
) -> Graph:
    """Parse an authoring-module ``source`` string into a :class:`Graph`.

    The inverse of :func:`to_composite`: module-level imports resolve call names
    to registered node types; the composite's single-assignment calls become
    nodes (variable name = node id), argument references become edges, and
    literal arguments become widget values. Positions are left ``null`` (layout
    is excluded from the bijection, ADR 0004 D6).

    ``module_name`` names the module the source belongs to; when given, calls
    to functions *defined at the top level of this same source* also resolve —
    to ``f"{module_name}.{name}"`` — so an authoring module whose ``@node``
    functions live next to its composite parses without self-imports. Composite
    parameters with literal defaults collapse to those defaults as widget
    values (see :func:`_param_defaults`).

    Raises:
        EngineError: the source contains a construct outside the dataflow subset
            (control flow, tuple targets, argument unpacking, …) or references an
            unknown/unimported node type (ADR 0004 D7).
    """
    registry = registry or DEFAULT_REGISTRY
    tree = ast.parse(source)

    composite = find_composite(tree)
    imports = _import_map(tree)
    if module_name is not None:
        for stmt in tree.body:
            if isinstance(stmt, ast.FunctionDef) and stmt is not composite:
                imports.setdefault(stmt.name, f"{module_name}.{stmt.name}")
    params = _param_defaults(composite)

    graph = Graph()
    node_ids: set[str] = set()
    pending_edges: list[tuple[str, str, str, str]] = []

    for stmt in composite.body:
        if isinstance(stmt, ast.Assign):
            _parse_assignment(stmt, imports, registry, graph, node_ids, pending_edges, params)
        elif isinstance(stmt, ast.Return):
            _parse_return(stmt, graph, node_ids)
        elif isinstance(stmt, ast.Pass):
            continue
        elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue  # docstring
        else:
            raise EngineError(
                f"unsupported statement {type(stmt).__name__} in composite body; "
                f"composites are straight-line dataflow — control flow lives in "
                f"node bodies (ADR 0004 D7)"
            )

    for src_id, socket, target, param in pending_edges:
        graph.connect(src_id, socket, target, param)

    return graph
