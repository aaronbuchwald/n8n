"""Headless graph engine — Nodezator's reusable core, UI-agnostic.

Four entry points make up the Phase-0 contract every later UI depends on:

* :func:`node_spec` — introspect a Python callable into a JSON node spec
  (inputs/outputs/widgets/docstring).
* :class:`Graph` — nodes + edges as plain, serialisable data.
* :func:`run` — execute a graph by a topological sweep.
* :func:`to_python` — emit a flat, runnable Python script from a graph.

The node-spec and graph JSON shapes are frozen in :mod:`engine.schema`
(``NODE_SPEC_SCHEMA`` / ``GRAPH_SCHEMA``, version ``engine.SCHEMA_VERSION``).

    >>> from engine import node_spec, Graph, run, to_python, NodeRegistry
    >>> reg = NodeRegistry()
    >>> reg.register(lambda x: x + 1, name="inc")           # doctest: +ELLIPSIS
    <function ...>
    >>> g = Graph().add("a", "inc", inputs={"x": 1})
    >>> run(g, reg).value("a")
    2
"""

from .errors import (
    CycleError,
    EngineError,
    GraphError,
    SchemaError,
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
