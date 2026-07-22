"""Headless graph engine — Nodezator's reusable core, UI-agnostic.

Four entry points make up the Phase-0 contract every later UI depends on:

* :func:`node_spec` — introspect a Python callable into a JSON node spec
  (inputs/outputs/widgets/docstring).
* :class:`Graph` — nodes + edges as plain, serialisable data.
* :func:`run` — execute a graph by a topological sweep.
* :func:`to_python` — emit a flat, runnable Python script from a graph.

Graphs are authored as ordinary Python with the decorator + tracing layer
(:func:`node`, :func:`graph`/:func:`main`) — calling a node inside a composite
records wiring instead of executing. Tracing produces the same :class:`Graph`
data model, so the frozen JSON contract in :mod:`engine.schema`
(``NODE_SPEC_SCHEMA`` / ``GRAPH_SCHEMA``, version ``engine.SCHEMA_VERSION``) is
unchanged.

    >>> from engine import node, main, run
    >>> @node
    ... def inc(x: int = 0) -> int:
    ...     return x + 1
    >>> @main
    ... def add_two(x: int = 0) -> int:
    ...     return inc(inc(x))
    >>> g = add_two.to_graph(x=1)
    >>> run(g).value(g.output_id)
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
from .errors import (
    CycleError,
    EngineError,
    GraphError,
    SchemaError,
    TracingError,
    UnknownNodeType,
    WaitingParentError,
)
from .execute import ExecutionResult, run
from .emit import to_python
from .graph import SCHEMA_VERSION, Edge, Graph, Node
from .ordering import topological_order
from .registry import DEFAULT_REGISTRY, NodeRegistry, RegisteredNode, register
from .schema import (
    GRAPH_SCHEMA,
    NODE_SPEC_SCHEMA,
    validate_graph,
    validate_node_spec,
)
from .spec import node_spec

__version__ = SCHEMA_VERSION

__all__ = [
    # entry points
    "node_spec",
    "Graph",
    "run",
    "to_python",
    # authoring (decorators + tracing)
    "node",
    "graph",
    "main",
    "trace",
    "NodeHandle",
    "NodePrimitive",
    "Composite",
    "TracingError",
    # model
    "Node",
    "Edge",
    "ExecutionResult",
    "topological_order",
    # registry
    "NodeRegistry",
    "RegisteredNode",
    "DEFAULT_REGISTRY",
    "register",
    # schema (frozen contract)
    "NODE_SPEC_SCHEMA",
    "GRAPH_SCHEMA",
    "validate_node_spec",
    "validate_graph",
    "SCHEMA_VERSION",
    # errors
    "EngineError",
    "SchemaError",
    "GraphError",
    "UnknownNodeType",
    "CycleError",
    "WaitingParentError",
    "__version__",
]
