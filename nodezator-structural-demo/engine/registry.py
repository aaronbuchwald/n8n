"""``NodeRegistry`` — maps node-type names to callables + their specs.

A :class:`~engine.graph.Graph` stores only *type names* (plain data). To run or
export it, something must resolve each name to the real callable and its
:func:`~engine.spec.node_spec`. That binding lives here, kept separate from the
graph so the same graph JSON can be driven by different registries (e.g. a mock
RFEM node swapped for the real one — a one-line registration change).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from .errors import UnknownNodeType
from .spec import node_spec


@dataclass(frozen=True)
class RegisteredNode:
    """A node type: its name, the callable, and the introspected spec."""

    name: str
    fn: Callable[..., Any]
    spec: dict


class NodeRegistry:
    """A collection of node types keyed by name."""

    def __init__(self) -> None:
        self._entries: dict[str, RegisteredNode] = {}

    def register(
        self,
        fn: Callable[..., Any],
        *,
        name: Optional[str] = None,
        title: Optional[str] = None,
        outputs: Optional[list] = None,
        third_party_import: Optional[str] = None,
        stdlib_import: Optional[str] = None,
    ) -> Callable[..., Any]:
        """Register ``fn`` as a node type and return it (usable as a decorator).

        ``outputs`` overrides output-socket inference for functions that return a
        keyed ``dict`` but only declare ``-> dict`` (see :func:`engine.spec.node_spec`).
        ``third_party_import`` / ``stdlib_import`` are the import lines emitted
        into exported Python so the generated script is self-contained.
        """
        resolved = name or fn.__name__
        spec = node_spec(
            fn,
            name=resolved,
            title=title,
            outputs=outputs,
            imports={"stdlib": stdlib_import, "thirdParty": third_party_import},
        )
        self._entries[resolved] = RegisteredNode(name=resolved, fn=fn, spec=spec)
        return fn

    def __contains__(self, name: str) -> bool:
        return name in self._entries

    def get(self, name: str) -> RegisteredNode:
        try:
            return self._entries[name]
        except KeyError:
            raise UnknownNodeType(f"node type {name!r} is not registered") from None

    def callable(self, name: str) -> Callable[..., Any]:
        return self.get(name).fn

    def spec(self, name: str) -> dict:
        return self.get(name).spec

    def specs(self) -> dict[str, dict]:
        """All specs keyed by name — the palette a UI renders from."""
        return {name: entry.spec for name, entry in self._entries.items()}

    def names(self) -> list[str]:
        return list(self._entries)


# A process-wide default so ``run(graph)`` / ``to_python(graph)`` work without
# threading a registry through every call. Explicit registries are still
# preferred for isolation (tests, multiple node packs).
DEFAULT_REGISTRY = NodeRegistry()


def register(fn: Callable[..., Any] = None, **kwargs) -> Callable[..., Any]:
    """Register a node type on :data:`DEFAULT_REGISTRY` (decorator-friendly)."""
    if fn is None:
        return lambda f: DEFAULT_REGISTRY.register(f, **kwargs)
    return DEFAULT_REGISTRY.register(fn, **kwargs)
