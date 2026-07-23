"""Headless graph engine — Nodezator's reusable core, UI-agnostic.

Entry points:

* :func:`node_spec` — introspect a Python callable into a JSON node spec.
* :class:`Graph` — nodes + edges as plain, serialisable data.
* :func:`bind` — resolve a graph against a registry into a validated,
  reference-linked :class:`~engine.bind.BoundGraph` (the one string→object step).
* :func:`run` — execute a graph (binds it first).
* :func:`to_python` — emit a flat, runnable Python script from a graph.
* :func:`to_composite` / :func:`from_composite` — the Graph ⟷ authoring-module
  bijection (ADR 0004): emit/parse the ``@main`` wiring composite.

Graphs are authored as ordinary Python with the decorator + tracing layer
(:func:`node`, :func:`graph`/:func:`main`) — calling a node inside a composite
records wiring instead of executing. Tracing produces the same :class:`Graph`
data model, so the JSON contract in :mod:`engine.schema` is unchanged.

    >>> from engine import node, main, run
    >>> @node
    ... def inc(x: int = 0) -> int:
    ...     return x + 1
    >>> @main
    ... def add_two(x: int = 0) -> int:
    ...     return inc(inc(x))
    >>> g = add_two.to_graph(x=1)
    >>> run(g).value(g.output["node"], g.output["socket"])
    3
"""

from .authoring import (
    Composite,
    NodeHandle,
    NodePrimitive,
    graph,
    main,
    node,
    trace,
)
from .bind import BoundGraph, BoundNode, bind
from .errors import (
    BindError,
    CycleError,
    DuplicateNodeType,
    EngineError,
    GraphError,
    NodeExecutionError,
    SchemaError,
    TracingError,
    UnknownNodeType,
    UserError,
)
from .execute import ExecutionResult, run
from .emit import to_python
from .composite import (
    composite_call_names,
    find_composite,
    from_composite,
    to_composite,
    wiring_lines,
)
from .graph import Edge, Graph, Node
from .ordering import topological_order, topological_sort
from .registry import DEFAULT_REGISTRY, NodeRegistry, RegisteredNode
from .schema import (
    GRAPH_SCHEMA,
    NODE_SPEC_SCHEMA,
    validate_graph,
    validate_node_spec,
)
from .spec import DerivedInputs, Widget, effective_inputs, node_spec
from .version import SCHEMA_VERSION

__version__ = SCHEMA_VERSION

__all__ = [
    # entry points
    "node_spec",
    "Widget",
    "DerivedInputs",
    "effective_inputs",
    "Graph",
    "bind",
    "run",
    "to_python",
    "to_composite",
    "from_composite",
    "wiring_lines",
    "find_composite",
    "composite_call_names",
    # authoring (decorators + tracing)
    "node",
    "graph",
    "main",
    "trace",
    "NodeHandle",
    "NodePrimitive",
    "Composite",
    # model
    "Node",
    "Edge",
    "BoundGraph",
    "BoundNode",
    "ExecutionResult",
    "topological_order",
    "topological_sort",
    # registry
    "NodeRegistry",
    "RegisteredNode",
    "DEFAULT_REGISTRY",
    # schema / contract
    "NODE_SPEC_SCHEMA",
    "GRAPH_SCHEMA",
    "validate_node_spec",
    "validate_graph",
    "SCHEMA_VERSION",
    # errors
    "EngineError",
    "UserError",
    "SchemaError",
    "GraphError",
    "UnknownNodeType",
    "DuplicateNodeType",
    "BindError",
    "CycleError",
    "TracingError",
    "NodeExecutionError",
    "__version__",
]
