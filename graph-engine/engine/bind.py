"""``bind(graph, registry)`` — resolve a string-keyed graph into a runnable form.

This is the single choke point between *graph as portable data* and *graph as
something you run or export*. It resolves every id/socket/param string exactly
once, validates the whole graph up front, and hands back a
:class:`BoundGraph` whose nodes link to their upstream nodes **by reference**.

Everything the reviewer flagged about "precarious strings" lives or dies here:
after a successful ``bind`` there are no unresolved names left, and every
structural error (unknown type, bad socket, duplicate input edge, missing
required input, cycle) has already been raised — never mid-execution.

    BoundGraph = bind(graph, registry)   # validated, reference-linked, ephemeral
    run(BoundGraph) / to_python(BoundGraph)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from .errors import BindError, UnknownNodeType, UserError
from .graph import Edge, Graph
from .ordering import topological_order
from .registry import DEFAULT_REGISTRY, NodeRegistry, RegisteredNode
from .spec import effective_inputs


@dataclass
class BoundNode:
    """A validated node instance, linked to its inputs by reference.

    ``inputs_spec`` is the node's **effective** input list — the static signature
    sockets plus any derived sockets computed once here in bind pass 1 (ADR 0007).
    For a non-dynamic node it equals ``spec["inputs"]``. Emit and execute consume
    it so the derived sockets are never re-derived downstream.
    """

    id: str
    entry: RegisteredNode
    literals: dict[str, Any] = field(default_factory=dict)
    # param name -> (upstream node, its output socket)
    wired: dict[str, tuple["BoundNode", str]] = field(default_factory=dict)
    inputs_spec: list[dict] = field(default_factory=list)

    @property
    def spec(self) -> dict:
        return self.entry.spec

    @property
    def type(self) -> str:
        return self.entry.id


# Diagnostic code for a required input left unsatisfied in a draft graph.
# Reuses the ``{code, message, nodeId, ...}`` structured-error vocabulary so a UI
# can badge it the same way it badges bind errors — here scoped to the exact
# input rather than an edge (a missing input has no wire to point at).
INCOMPLETE_INPUT = "incompleteInput"


@dataclass
class BoundGraph:
    """Topologically ordered, reference-linked, validated graph.

    ``incomplete`` is always empty after a full ``bind`` (a missing required
    input is a hard :class:`BindError` then). Under ``bind(..., partial=True)``
    it collects one structured diagnostic per unsatisfied required input instead
    of raising, so an in-progress draft can still validate and be saved (ADR 0011
    D6). Each diagnostic is ``{"code", "message", "nodeId", "input"}``.
    """

    nodes: list[BoundNode]
    by_id: dict[str, BoundNode]
    registry: NodeRegistry
    output: Optional[tuple[BoundNode, str]] = None
    incomplete: list[dict] = field(default_factory=list)


def _edge_dict(edge: Edge) -> dict:
    """The edge as portable ``{source, sourceOutput, target, targetInput}`` — the
    same wire shape the graph JSON uses — so an error can badge the exact edge."""
    return edge.to_dict()


def _ensure_json(node_id: str, param: str, value: Any) -> None:
    try:
        json.dumps(value)
    except TypeError:
        raise BindError(
            f"node {node_id!r} input {param!r} has a non-serialisable literal "
            f"{value!r} ({type(value).__name__}); pass a JSON value or wire it "
            f"from a node",
            node_id=node_id,
        ) from None


def bind(
    graph: Graph,
    registry: Optional[NodeRegistry] = None,
    *,
    partial: bool = False,
) -> BoundGraph:
    """Validate ``graph`` against ``registry`` and return a :class:`BoundGraph`.

    Args:
        partial: draft/edit-mode validation (ADR 0011 D6). When ``True``, a
            required input that is neither wired nor given a literal is
            **tolerated** — collected on ``BoundGraph.incomplete`` as a structured
            ``{"code", "message", "nodeId", "input"}`` diagnostic instead of
            raising. Every other check (unknown type/socket/param, non-serialisable
            literal, double-wire, cycle, bad output) stays a hard error, so a
            half-built graph can validate and save while genuinely broken wiring
            still fails loudly. ``False`` (the default) is unchanged: the first
            unsatisfied required input is a :class:`BindError`.

    Raises:
        UnknownNodeType: a node references an unregistered type.
        BindError: a literal is non-serialisable / targets an unknown input, an
            edge references an unknown node/socket/param, an input is wired
            twice, or (when ``partial`` is ``False``) a required input is
            unprovided.
        CycleError: the graph contains a cycle.
    """
    registry = registry or DEFAULT_REGISTRY

    # An edge targeting a dynamic node's deriving param must be rejected as such
    # (ADR 0007 D2) — and *before* pass-1 literal validation, because a wired
    # deriving param leaves its value unknown, so derivation yields nothing and
    # the node's derived-symbol literals would otherwise look "unknown" first.
    edge_by_target_input: dict[tuple[str, str], Edge] = {}
    for edge in graph.edges:
        edge_by_target_input.setdefault((edge.target, edge.target_input), edge)

    # -- pass 1: resolve node types, validate literals --------------------
    bound_by_id: dict[str, BoundNode] = {}
    for node in graph.nodes:
        try:
            entry = registry.get(node.type)  # UnknownNodeType if absent
        except UnknownNodeType as exc:
            # Enrich with the graph node id — the registry only knows the type.
            exc.node_id = node.id
            raise
        if entry.dynamic is not None:
            wired_edge = edge_by_target_input.get((node.id, entry.dynamic.param))
            if wired_edge is not None:
                raise BindError(
                    f"the deriving input {entry.dynamic.param!r} of a dynamic node "
                    f"must be a widget literal, not wired",
                    node_id=node.id,
                    edge=_edge_dict(wired_edge),
                )
        literals = dict(node.inputs)
        # Effective inputs = static sockets + derived entries from the deriving
        # literal (ADR 0007). Computed once here; a deriver failure becomes a
        # BindError badging the node, before anything executes.
        try:
            inputs_spec = effective_inputs(entry.spec, entry.dynamic, literals)
        except UserError as exc:
            raise BindError(str(exc), node_id=node.id) from exc
        input_names = {i["name"] for i in inputs_spec}
        for param, value in node.inputs.items():
            if param not in input_names:
                raise BindError(
                    f"node {node.id!r} sets input {param!r}, which is not a "
                    f"parameter of {node.type!r}",
                    node_id=node.id,
                )
            _ensure_json(node.id, param, value)
        bound_by_id[node.id] = BoundNode(
            id=node.id, entry=entry, literals=literals, inputs_spec=inputs_spec
        )

    # -- pass 2: resolve + validate edges ---------------------------------
    for edge in graph.edges:
        edge_ctx = _edge_dict(edge)
        source = bound_by_id.get(edge.source)
        target = bound_by_id.get(edge.target)
        if source is None or target is None:
            # Badge whichever endpoint is missing (source first if both are).
            missing = edge.source if source is None else edge.target
            raise BindError(
                f"edge {edge.source!r}->{edge.target!r} references an unknown node",
                node_id=missing,
                edge=edge_ctx,
            )
        source_sockets = {o["name"] for o in source.spec["outputs"]}
        if edge.source_output not in source_sockets:
            raise BindError(
                f"edge from {edge.source!r} reads output {edge.source_output!r}, "
                f"which is not an output of {source.type!r} "
                f"(has: {', '.join(sorted(source_sockets))})",
                node_id=edge.source,
                edge=edge_ctx,
            )
        # (A wired deriving param is already rejected in pass 1, ADR 0007 D2.)
        target_inputs = {i["name"] for i in target.inputs_spec}
        if edge.target_input not in target_inputs:
            raise BindError(
                f"edge into {edge.target!r} feeds input {edge.target_input!r}, "
                f"which is not a parameter of {target.type!r}",
                node_id=edge.target,
                edge=edge_ctx,
            )
        if edge.target_input in target.wired:
            raise BindError(
                f"input {edge.target_input!r} of node {edge.target!r} is wired "
                f"by more than one edge",
                node_id=edge.target,
                edge=edge_ctx,
            )
        target.wired[edge.target_input] = (source, edge.source_output)
        # An edge wins over a widget literal for the same input.
        target.literals.pop(edge.target_input, None)

    # -- pass 3: every required input must be satisfied -------------------
    # Derived sockets inherit Python's required/optional semantics (ADR 0007 #5):
    # a socket with no default is required and fails loudly when unsatisfied; one
    # with a default is optional and binds unsatisfied (execute uses the default).
    # In ``partial`` mode this pass is collected, not fatal (ADR 0011 D6): the only
    # difference between run-validation and edit-validation is whether an
    # unsatisfied required input hard-fails or is badged for the UI.
    incomplete: list[dict] = []
    for bound in bound_by_id.values():
        for inp in bound.inputs_spec:
            if not inp["required"]:
                continue
            name = inp["name"]
            if name not in bound.wired and name not in bound.literals:
                message = (
                    f"required input {name!r} of node {bound.id!r} "
                    f"({bound.type}) is neither wired nor given a value"
                )
                if not partial:
                    raise BindError(message, node_id=bound.id)
                incomplete.append(
                    {
                        "code": INCOMPLETE_INPUT,
                        "message": message,
                        "nodeId": bound.id,
                        "input": name,
                    }
                )

    # -- pass 4: order + resolve the output socket ------------------------
    order = topological_order(graph)  # CycleError if cyclic
    ordered = [bound_by_id[nid] for nid in order]

    output: Optional[tuple[BoundNode, str]] = None
    if graph.output is not None:
        onode = bound_by_id.get(graph.output.get("node"))
        socket = graph.output.get("socket")
        if onode is None:
            raise BindError(
                f"graph output references unknown node {graph.output.get('node')!r}"
            )
        if socket not in {o["name"] for o in onode.spec["outputs"]}:
            raise BindError(
                f"graph output socket {socket!r} is not an output of {onode.type!r}",
                node_id=onode.id,
            )
        output = (onode, socket)

    return BoundGraph(
        nodes=ordered,
        by_id=bound_by_id,
        registry=registry,
        output=output,
        incomplete=incomplete,
    )


def validate_edit(
    graph: Graph, registry: Optional[NodeRegistry] = None
) -> list[dict]:
    """Edit-mode validation entry: the draft's incomplete-input diagnostics.

    Binds ``graph`` in ``partial`` mode and returns the structured ``incomplete``
    list (``{"code", "message", "nodeId", "input"}`` per unsatisfied required
    input). Hard structural errors (unknown type/socket/param, double-wire,
    cycle, bad output) still raise, exactly as in a run-mode bind — edit mode
    only softens the *missing required input* case. This is the engine capability
    the ``POST /api/graphs/validate`` ``mode:"edit"`` path (ADR 0011 W3) sits on
    top of; the empty list means "complete enough to run".
    """
    return bind(graph, registry, partial=True).incomplete
