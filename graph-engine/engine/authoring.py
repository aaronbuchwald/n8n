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

* **primitive** (``@node``) — an opaque callable, registered by its
  collision-proof ``module.qualname`` id. Under a trace it records a single node
  and returns a :class:`NodeHandle`; called normally it just runs.
* **composite** (``@graph`` / ``@main``) — its body is other nodes. Under a
  trace it is **inlined**, so the resulting :class:`~engine.graph.Graph`
  contains only primitives. ``@main`` is ``@graph(entry=True)``: the entry flag
  marks the default view, nothing more.

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
from .spec import DerivedInputs, Renderer, Widget

# One trace at a time per thread. ``None`` means "eager" (calls execute).
_state = threading.local()


def _current() -> Optional["_TraceState"]:
    return getattr(_state, "current", None)


class NodeHandle:
    """A placeholder for one output socket of a node being traced.

    Attribute/item access selects a named output socket of a multi-output node
    (``fields.force_kN`` / ``fields["force_kN"]``). Using a handle where a real
    value is needed (``if h:``, ``for x in h``) raises — the dataflow boundary.
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

    def add_node(self, short_name: str, type_id: str, inputs: dict[str, Any]) -> str:
        n = self._counts.get(short_name, 0) + 1
        self._counts[short_name] = n
        node_id = short_name if n == 1 else f"{short_name}_{n}"
        self.graph.add(node_id, type_id, inputs=inputs)
        return node_id


class NodePrimitive:
    """Wrapper returned by ``@node``. Records under trace, runs when eager."""

    def __init__(self, fn: Callable[..., Any], entry) -> None:
        self.fn = fn
        self.entry = entry
        self.id = entry.id
        self.name = entry.name
        self.spec = entry.spec
        functools.update_wrapper(self, fn)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        state = _current()
        if state is None:
            return self.fn(*args, **kwargs)  # eager

        signature = inspect.signature(self.fn)
        bound = signature.bind_partial(*args, **kwargs)
        # A dynamic node's derived symbols arrive as **kwargs, which bind_partial
        # folds into a single dict under the VAR_KEYWORD parameter name. Flatten
        # that dict so each symbol becomes its own literal or edge — otherwise a
        # NodeHandle buried inside it would never become a wire (ADR 0007 D6).
        var_keyword = next(
            (p.name for p in signature.parameters.values() if p.kind == p.VAR_KEYWORD),
            None,
        )
        literals: dict[str, Any] = {}
        edges: list[tuple[str, NodeHandle]] = []
        for pname, value in bound.arguments.items():
            if pname == var_keyword and isinstance(value, dict):
                for kname, kvalue in value.items():
                    if isinstance(kvalue, NodeHandle):
                        edges.append((kname, kvalue))
                    else:
                        literals[kname] = kvalue
                continue
            if isinstance(value, NodeHandle):
                edges.append((pname, value))
            else:
                literals[pname] = value

        node_id = state.add_node(self.name, self.id, literals)
        for pname, handle in edges:
            if handle.socket is None:
                raise TracingError(
                    f"node {handle.node_id!r} has multiple outputs — pick one "
                    f"(e.g. handle.<socket>) before wiring it into {self.name!r}"
                )
            state.graph.connect(handle.node_id, handle.socket, node_id, pname)

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
        # Eager it computes for real; under a trace the child calls record.
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
    widgets: Optional[dict[str, Widget]] = None,
    dynamic: Optional[DerivedInputs] = None,
    renderer: Optional[Renderer] = None,
    registry: Optional[NodeRegistry] = None,
    replace: bool = False,
) -> Any:
    """Decorate a function as a primitive node type (registers + introspects).

    The type id is ``module.qualname`` (collision-proof); ``outputs=[...]``
    declares named output sockets (default: one ``result`` socket).
    ``widgets={"param": Widget(...)}`` declares editing-widget contracts on named
    inputs (ADR 0005 A-D2), threaded into each input spec's ``widget`` field.
    ``dynamic=DerivedInputs(...)`` (ADR 0007) declares extra input sockets derived
    from one literal parameter's value; such a node needs a ``**kwargs``
    receptacle for the derived values.
    ``renderer=Renderer(kind, **config)`` (ADR 0010 D1) declares one whole-node
    rendering contract, threaded into the spec's top-level ``renderer`` field; a
    ``socket`` config key is validated against ``outputs`` at import time.
    """

    def wrap(target: Callable[..., Any]) -> NodePrimitive:
        reg = registry or DEFAULT_REGISTRY
        entry = reg.register(
            target,
            name=name,
            title=title,
            outputs=outputs,
            widgets=widgets,
            dynamic=dynamic,
            renderer=renderer,
            replace=replace,
        )
        return NodePrimitive(target, entry)

    return wrap if fn is None else wrap(fn)


def graph(fn: Optional[Callable[..., Any]] = None, *, entry: bool = False) -> Any:
    """Decorate a composition function as a composite node."""

    def wrap(target: Callable[..., Any]) -> Composite:
        return Composite(target, entry=entry)

    return wrap if fn is None else wrap(fn)


def _derive_title(qualname: str) -> str:
    """Un-snake-case a composite's function name (``readings_report`` → ``Readings report``)."""
    words = qualname.replace("_", " ").strip()
    return (words[:1].upper() + words[1:]) if words else qualname


class EntryPointRegistry:
    """Process-wide registry of ``@main`` composites — the viewable entry points.

    A sibling of :data:`~engine.registry.DEFAULT_REGISTRY` for *composites*
    (ADR 0009 D2): whatever is imported and marked ``@main`` is an entry point.
    ``@graph`` composites stay unlisted. The dedup key is the **module** —
    re-importing an edited module re-registers, mirroring
    ``NodeRegistry.unregister_module`` semantics for nodes.
    """

    def __init__(self) -> None:
        self._by_module: dict[str, dict[str, Any]] = {}

    def register(self, composite: Composite, *, title: Optional[str] = None) -> dict[str, Any]:
        fn = composite.fn
        module = getattr(fn, "__module__", None) or "?"
        qualname = getattr(fn, "__qualname__", None) or getattr(fn, "__name__", "?")
        doc = inspect.getdoc(fn)
        entry: dict[str, Any] = {
            "module": module,
            "qualname": qualname,
            "file": inspect.getsourcefile(fn),
            "doc": doc.splitlines()[0] if doc else None,
            "title": title if title is not None else _derive_title(qualname),
        }
        self._by_module[module] = entry
        return entry

    def entries(self) -> list[dict[str, Any]]:
        """All registered entry points (copies), ordered by module name."""
        return [dict(e) for _, e in sorted(self._by_module.items())]

    def get(self, module: str) -> dict[str, Any]:
        return dict(self._by_module[module])

    def __contains__(self, module: str) -> bool:
        return module in self._by_module

    def unregister_module(self, module: str) -> bool:
        """Drop the entry registered by ``module``; True when one existed."""
        return self._by_module.pop(module, None) is not None


ENTRY_POINTS = EntryPointRegistry()


def main(fn: Optional[Callable[..., Any]] = None, *, title: Optional[str] = None) -> Any:
    """A composite flagged as a top-level entry/view: ``graph(entry=True)``.

    Registers the composite in :data:`ENTRY_POINTS` at decoration time (ADR
    0009 D2) so a server can list every viewable program. ``title`` overrides
    the derived display title (the un-snake-cased function name).
    """

    def wrap(target: Callable[..., Any]) -> Composite:
        composite = graph(target, entry=True)
        ENTRY_POINTS.register(composite, title=title)
        return composite

    return wrap if fn is None else wrap(fn)


def trace(composite: Composite, **inputs: Any) -> Graph:
    """Run ``composite``'s body under trace and return the built graph.

    The graph's ``output`` records which socket the composite returned. Nested
    composites are inlined, so the graph is all primitives. Save/restore of the
    trace state makes tracing reentrant (a composite may build a subgraph).
    """
    previous = _current()
    state = _TraceState()
    _state.current = state
    try:
        signature = inspect.signature(composite.fn)
        bound = signature.bind_partial(**inputs)
        bound.apply_defaults()
        result = composite.fn(*bound.args, **bound.kwargs)
    finally:
        _state.current = previous

    built = state.graph
    if isinstance(result, NodeHandle) and result.socket is not None:
        built.output = {"node": result.node_id, "socket": result.socket}
    return built
