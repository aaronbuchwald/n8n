"""Engine error types.

Kept deliberately small and dependency-free so the headless core can be
imported anywhere without pulling in a UI or heavy libraries.
"""


class EngineError(Exception):
    """Base class for all headless-engine errors."""


class SchemaError(EngineError):
    """A node-spec or graph document violated the frozen JSON schema."""


class GraphError(EngineError):
    """The graph is structurally invalid (unknown node type, bad edge, cycle)."""


class UnknownNodeType(GraphError):
    """A graph node references a type that isn't in the registry."""


class BindError(GraphError):
    """Binding a graph to a registry failed validation (bad socket/param/edge).

    Raised by :func:`engine.bind.bind` *before* any node runs, so structural
    mistakes surface as static errors an editor can show, not mid-execution.
    """


class DuplicateNodeType(EngineError):
    """A node type id was registered twice with a different callable."""


class CycleError(GraphError):
    """The graph contains a cycle and cannot be ordered/executed."""


class NodeExecutionError(EngineError):
    """A node's callable raised while the graph was running.

    Carries the offending ``node_id`` so a UI can highlight it; the original
    exception is available as ``__cause__``.
    """

    def __init__(self, node_id: str, node_type: str, cause: BaseException) -> None:
        self.node_id = node_id
        self.node_type = node_type
        super().__init__(f"node {node_id!r} ({node_type}) raised {type(cause).__name__}: {cause}")


class TracingError(EngineError):
    """A traced node value was used where a concrete value is required.

    Raised when a ``@graph`` composite tries to branch/iterate on the output of
    another node during tracing. Composites are pure dataflow wiring; imperative
    logic (loops, branches, mutation) belongs inside a ``@node`` body.
    """
