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


class CycleError(GraphError):
    """The graph contains a cycle and cannot be ordered/executed."""


class WaitingParentError(EngineError):
    """Raised while resolving a node whose parent output isn't ready yet.

    Mirrors Nodezator's ``WaitingParentException``: the lazy sweep catches it
    and retries the node on a later pass. The clean topological executor uses a
    real ordering instead, but the type is kept as the documented contract.
    """
