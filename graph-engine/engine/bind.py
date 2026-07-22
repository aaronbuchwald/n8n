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

from .errors import BindError
from .graph import Graph
from .ordering import topological_order
from .registry import DEFAULT_REGISTRY, NodeRegistry, RegisteredNode


@dataclass
class BoundNode:
    """A validated node instance, linked to its inputs by reference."""

    id: str
    entry: RegisteredNode
    literals: dict[str, Any] = field(default_factory=dict)
    # param name -> (upstream node, its output socket)
    wired: dict[str, tuple["BoundNode", str]] = field(default_factory=dict)

    @property
    def spec(self) -> dict:
        return self.entry.spec

    @property
    def type(self) -> str:
        return self.entry.id


@dataclass
class BoundGraph:
    """Topologically ordered, reference-linked, validated graph."""

    nodes: list[BoundNode]
    by_id: dict[str, BoundNode]
    registry: NodeRegistry
    output: Optional[tuple[BoundNode, str]] = None


def _ensure_json(node_id: str, param: str, value: Any) -> None:
    try:
        json.dumps(value)
    except TypeError:
        raise BindError(
            f"node {node_id!r} input {param!r} has a non-serialisable literal "
            f"{value!r} ({type(value).__name__}); pass a JSON value or wire it "
            f"from a node"
        ) from None


def bind(graph: Graph, registry: Optional[NodeRegistry] = None) -> BoundGraph:
    """Validate ``graph`` against ``registry`` and return a :class:`BoundGraph`.

    Raises:
        UnknownNodeType: a node references an unregistered type.
        BindError: a literal is non-serialisable / targets an unknown input, an
            edge references an unknown node/socket/param, an input is wired
            twice, or a required input is unprovided.
        CycleError: the graph contains a cycle.
    """
    registry = registry or DEFAULT_REGISTRY

    # -- pass 1: resolve node types, validate literals --------------------
    bound_by_id: dict[str, BoundNode] = {}
    for node in graph.nodes:
        entry = registry.get(node.type)  # UnknownNodeType if absent
        input_names = {i["name"] for i in entry.spec["inputs"]}
        for param, value in node.inputs.items():
            if param not in input_names:
                raise BindError(
                    f"node {node.id!r} sets input {param!r}, which is not a "
                    f"parameter of {node.type!r}"
                )
            _ensure_json(node.id, param, value)
        bound_by_id[node.id] = BoundNode(id=node.id, entry=entry, literals=dict(node.inputs))

    # -- pass 2: resolve + validate edges ---------------------------------
    for edge in graph.edges:
        source = bound_by_id.get(edge.source)
        target = bound_by_id.get(edge.target)
        if source is None or target is None:
            raise BindError(
                f"edge {edge.source!r}->{edge.target!r} references an unknown node"
            )
        source_sockets = {o["name"] for o in source.spec["outputs"]}
        if edge.source_output not in source_sockets:
            raise BindError(
                f"edge from {edge.source!r} reads output {edge.source_output!r}, "
                f"which is not an output of {source.type!r} "
                f"(has: {', '.join(sorted(source_sockets))})"
            )
        target_inputs = {i["name"] for i in target.spec["inputs"]}
        if edge.target_input not in target_inputs:
            raise BindError(
                f"edge into {edge.target!r} feeds input {edge.target_input!r}, "
                f"which is not a parameter of {target.type!r}"
            )
        if edge.target_input in target.wired:
            raise BindError(
                f"input {edge.target_input!r} of node {edge.target!r} is wired "
                f"by more than one edge"
            )
        target.wired[edge.target_input] = (source, edge.source_output)
        # An edge wins over a widget literal for the same input.
        target.literals.pop(edge.target_input, None)

    # -- pass 3: every required input must be satisfied -------------------
    for bound in bound_by_id.values():
        for inp in bound.spec["inputs"]:
            if not inp["required"]:
                continue
            name = inp["name"]
            if name not in bound.wired and name not in bound.literals:
                raise BindError(
                    f"required input {name!r} of node {bound.id!r} "
                    f"({bound.type}) is neither wired nor given a value"
                )

    # -- pass 4: order + resolve the output socket ------------------------
    order = topological_order(graph)  # CycleError if cyclic
    ordered = [bound_by_id[nid] for nid in order]

    output: Optional[tuple[BoundNode, str]] = None
    if graph.output is not None:
        onode = bound_by_id.get(graph.output.get("node"))
        socket = graph.output.get("socket")
        if onode is None:
            raise BindError(f"graph output references unknown node {graph.output.get('node')!r}")
        if socket not in {o["name"] for o in onode.spec["outputs"]}:
            raise BindError(f"graph output socket {socket!r} is not an output of {onode.type!r}")
        output = (onode, socket)

    return BoundGraph(nodes=ordered, by_id=bound_by_id, registry=registry, output=output)
