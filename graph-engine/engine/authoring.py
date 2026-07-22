"""Decorator + tracing authoring layer: write graphs as ordinary Python.

Decorate leaf functions with ``@node`` and a composition function with
``@graph`` (or ``@main``). The composition's body *calls* nodes; tracing turns
each call into graph wiring instead of executing it, so the code **is** the
graph:

    @node
    def read_values(path: str = "readings.csv") -> list: ...
    @node
    def total(values: list) -> float: ...
    @node
    def average(values: list) -> float: ...
    @node
    def render_summary(total: float, average: float) -> str: ...

    @main
    def readings_report(path: str = "readings.csv") -> str:
        values = read_values(path)
        return render_summary(total(values), average(values))

    g = readings_report.to_graph()      # -> a Graph (the frozen data model)

Two node flavours, one model:

* **primitive** (``@node``) — an opaque callable. Under a trace it records a
  single node and returns a :class:`NodeHandle`; called normally it just runs.
* **composite** (``@graph`` / ``@main``) — its body is other nodes. Under a
  trace it is **inlined** (its body runs, recording the child nodes), so the
  resulting :class:`~engine.graph.Graph` contains only primitives — `run` and
  `to_python` never see a composite. ``@main`` is just ``@graph(entry=True)``:
  the entry flag marks the default view, nothing more.

Imperative logic (loops, branches, mutation) lives *inside* a primitive body;
composites are pure wiring. Branching on a traced value raises
:class:`~engine.errors.TracingError`.
"""

from __future__ import annotations

import functools
import inspect
import threading
from typing import Any, Callable, Optional

from .errors import TracingError
from .graph import Graph
from .registry import DEFAULT_REGISTRY, NodeRegistry

# One trace at a time per thread. ``None`` means "eager" (calls execute).
_state = threading.local()


def _current() -> Optional["_TraceState"]:
    return getattr(_state, "current", None)


class NodeHandle:
    """A placeholder for one output socket of a node being traced.

    Attribute/item access selects a named output socket of a multi-output node
    (``fields.force_kN`` / ``fields["force_kN"]``). Using a handle where a real
    value is needed (``if h:``, ``for x in h``) raises — that's the dataflow
    boundary.
    """

    __slots__ = ("node_id", "socket")

    def __init__(self, node_id: str, socket: Optional[str] = None) -> None:
        self.node_id = node_id
        self.socket = socket

    def __getattr__(self, name: str) -> "NodeHandle":
        if name.startswith("_"):
            raise AttributeError(name)
        return NodeHandle(self.node_id, name)

    def __getitem__(self, name: str) -> "NodeHandle":
        return NodeHandle(self.node_id, name)

    def __bool__(self):
        raise TracingError(
            "cannot branch on a traced node value — put control flow inside a "
            "@node body; composites are pure dataflow wiring"
        )

    def __iter__(self):
        raise TracingError(
            "cannot iterate a traced node value — put loops inside a @node body"
        )

    def __repr__(self) -> str:
        return f"<NodeHandle {self.node_id}.{self.socket or '?'}>"


class _TraceState:
    """Accumulates nodes/edges while a composite body runs under trace."""

    def __init__(self) -> None:
        self.graph = Graph()
        self._counts: dict[str, int] = {}

    def add_node(self, type_name: str, inputs: dict[str, Any]) -> str:
        n = self._counts.get(type_name, 0) + 1
        self._counts[type_name] = n
        node_id = type_name if n == 1 else f"{type_name}_{n}"
        self.graph.add(node_id, type_name, inputs=inputs)
        return node_id


class NodePrimitive:
    """Wrapper returned by ``@node``. Records under trace, runs when eager."""

    def __init__(self, fn: Callable[..., Any], name: str, spec: dict) -> None:
        self.fn = fn
        self.name = name
        self.spec = spec
        functools.update_wrapper(self, fn)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        state = _current()
        if state is None:
            return self.fn(*args, **kwargs)  # eager

        bound = inspect.signature(self.fn).bind_partial(*args, **kwargs)
        literals: dict[str, Any] = {}
        edges: list[tuple[str, NodeHandle]] = []
        for pname, value in bound.arguments.items():
            if isinstance(value, NodeHandle):
                edges.append((pname, value))
            else:
                literals[pname] = value

        node_id = state.add_node(self.name, literals)
        for pname, handle in edges:
            source_socket = handle.socket
            if source_socket is None:
                raise TracingError(
                    f"node {handle.node_id!r} has multiple outputs — pick one "
                    f"(e.g. handle.<socket>) before wiring it into {self.name!r}"
                )
            state.graph.connect(handle.node_id, source_socket, node_id, pname)

        outputs = self.spec["outputs"]
        socket = outputs[0]["name"] if len(outputs) == 1 else None
        return NodeHandle(node_id, socket)


class Composite:
    """Wrapper returned by ``@graph`` / ``@main``. Inlines under trace."""

    def __init__(self, fn: Callable[..., Any], *, entry: bool = False) -> None:
        self.fn = fn
        self.entry = entry
        functools.update_wrapper(self, fn)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        # Whether eager or nested inside another trace, run the body: eager it
        # computes for real; under a trace the child node calls record + inline.
        return self.fn(*args, **kwargs)

    def to_graph(self, **inputs: Any) -> Graph:
        """Trace this composite into a :class:`~engine.graph.Graph`."""
        return trace(self, **inputs)


def node(
    fn: Optional[Callable[..., Any]] = None,
    *,
    name: Optional[str] = None,
    title: Optional[str] = None,
    outputs: Optional[list] = None,
    third_party_import: Optional[str] = None,
    stdlib_import: Optional[str] = None,
    registry: Optional[NodeRegistry] = None,
) -> Any:
    """Decorate a function as a primitive node type (registers + introspects).

    If ``third_party_import`` is omitted it defaults to
    ``from <module> import <name>`` so exported Python resolves the callable.
    """

    def wrap(target: Callable[..., Any]) -> NodePrimitive:
        reg = registry or DEFAULT_REGISTRY
        resolved = name or target.__name__
        import_line = third_party_import
        if import_line is None and stdlib_import is None:
            import_line = f"from {target.__module__} import {target.__name__}"
        reg.register(
            target,
            name=resolved,
            title=title,
            outputs=outputs,
            third_party_import=import_line,
            stdlib_import=stdlib_import,
        )
        return NodePrimitive(target, resolved, reg.spec(resolved))

    return wrap if fn is None else wrap(fn)


def graph(fn: Optional[Callable[..., Any]] = None, *, entry: bool = False) -> Any:
    """Decorate a composition function as a composite node.

    A composite's body wires other nodes; :meth:`Composite.to_graph` traces it.
    """

    def wrap(target: Callable[..., Any]) -> Composite:
        return Composite(target, entry=entry)

    return wrap if fn is None else wrap(fn)


def main(fn: Optional[Callable[..., Any]] = None) -> Any:
    """A composite flagged as a top-level entry/view: ``graph(entry=True)``."""
    return graph(fn, entry=True) if fn is not None else graph(entry=True)


def trace(composite: Composite, **inputs: Any) -> Graph:
    """Run ``composite``'s body under trace and return the built graph.

    The returned graph carries a non-serialised ``output_id`` attribute naming
    the node whose value the composite returned (``None`` if it returned a
    non-handle). Nested composites are inlined, so the graph is all primitives.
    """
    state = _TraceState()
    _state.current = state
    try:
        signature = inspect.signature(composite.fn)
        bound = signature.bind_partial(**inputs)
        bound.apply_defaults()
        result = composite.fn(*bound.args, **bound.kwargs)
    finally:
        _state.current = None

    built = state.graph
    built.output_id = result.node_id if isinstance(result, NodeHandle) else None
    return built
