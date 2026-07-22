"""Engine error types.

Kept deliberately small and dependency-free so the headless core can be
imported anywhere without pulling in a UI or heavy libraries.
"""

from __future__ import annotations

from typing import Any, Optional


class EngineError(Exception):
    """Base class for all headless-engine errors."""


class UserError(EngineError):
    """A failure caused by *user* input, not a bug in the engine or a node.

    Raised when a value the user supplied is invalid in a way only the running
    node body can decide: a bad recipe shape or version, unsafe/unknown
    expression syntax, an unknown column/op/function, and similar (ADR 0005
    Part C). It stays an :class:`EngineError` so everything that already catches
    engine errors keeps catching it, and node packs raise this shared name
    instead of defining their own.
    """


class SchemaError(EngineError):
    """A node-spec or graph document violated the frozen JSON schema."""


class GraphError(EngineError):
    """The graph is structurally invalid (unknown node type, bad edge, cycle)."""


class UnknownNodeType(GraphError):
    """A graph node references a type that isn't in the registry.

    When raised during :func:`engine.bind.bind` it carries the offending
    ``node_id`` structurally (same attribute name as :class:`NodeExecutionError`)
    so a UI can badge the exact node rather than parsing it out of the message.
    """

    def __init__(self, message: str, *, node_id: Optional[str] = None) -> None:
        self.node_id = node_id
        super().__init__(message)


class BindError(GraphError):
    """Binding a graph to a registry failed validation (bad socket/param/edge).

    Raised by :func:`engine.bind.bind` *before* any node runs, so structural
    mistakes surface as static errors an editor can show, not mid-execution.

    The message text stays human-readable; the offending node and/or edge are
    *also* exposed structurally so a UI can badge them precisely:

    * ``node_id`` — the node the error attaches to (``None`` for whole-graph
      errors, e.g. an output referencing an unknown node).
    * ``edge`` — the offending connection as ``{source, sourceOutput, target,
      targetInput}`` when the error concerns an edge, else ``None``.
    """

    def __init__(
        self,
        message: str,
        *,
        node_id: Optional[str] = None,
        edge: Optional[dict] = None,
    ) -> None:
        self.node_id = node_id
        self.edge = edge
        super().__init__(message)


class DuplicateNodeType(EngineError):
    """A node type id was registered twice with a different callable."""


class CycleError(GraphError):
    """The graph contains a cycle and cannot be ordered/executed.

    ``node_ids`` lists the ids involved in the cycle (the nodes still stuck once
    Kahn's algorithm drains, or the single self-dependent node) so a UI can badge
    them all. Empty when the ids aren't known to the raiser.
    """

    def __init__(self, message: str, *, node_ids: Optional[list[str]] = None) -> None:
        self.node_ids = node_ids or []
        super().__init__(message)


class NodeExecutionError(EngineError):
    """A node's callable raised while the graph was running.

    Carries the offending ``node_id`` so a UI can highlight it; the original
    exception is available as ``__cause__``.

    ``message`` is the *raw* cause text (``str(cause)``, no wrapping prefix) —
    combined with the structural ``node_id``, a UI can badge and display the
    failure without parsing it out of ``str(exc)``, which stays the fuller
    "node X (type) raised Y: ..." form for logs/CLI (review 0005 #14).

    ``outputs``/``order`` carry the results of every node that finished
    executing *before* this one failed, so a caller doesn't have to discard
    them just because the run as a whole didn't succeed (review 0005 #6).
    """

    def __init__(
        self,
        node_id: str,
        node_type: str,
        cause: BaseException,
        *,
        outputs: Optional[dict[str, dict[str, Any]]] = None,
        order: Optional[list[str]] = None,
    ) -> None:
        self.node_id = node_id
        self.node_type = node_type
        self.message = str(cause)
        self.outputs = outputs or {}
        self.order = order or []
        super().__init__(f"node {node_id!r} ({node_type}) raised {type(cause).__name__}: {cause}")


class TracingError(EngineError):
    """A traced node value was used where a concrete value is required.

    Raised when a ``@graph`` composite tries to branch/iterate on the output of
    another node during tracing. Composites are pure dataflow wiring; imperative
    logic (loops, branches, mutation) belongs inside a ``@node`` body.
    """
