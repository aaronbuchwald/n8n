"""``NodeRegistry`` — maps node-type **ids** to callables + their specs.

A node type's canonical id is its ``module.qualname`` (from
:func:`engine.spec.node_spec`), not its bare name. So two functions both called
``total`` in different packages register as ``pkg_a.total`` and ``pkg_b.total``
and coexist — no silent clobber, no bogus collision error. Only registering the
*same* id twice with a *different* callable is an error (opt out with
``replace=True`` for notebook/REPL reloads).

A :class:`~engine.graph.Graph` stores only ids (plain data); the registry is
what resolves an id to the real callable + spec, kept separate so the same graph
can be driven by different registries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from .errors import DuplicateNodeType, UnknownNodeType
from .spec import Widget, node_spec


@dataclass(frozen=True)
class RegisteredNode:
    """A node type: canonical id, short name, the callable, and its spec."""

    id: str
    name: str
    fn: Callable[..., Any]
    spec: dict


class NodeRegistry:
    """A collection of node types keyed by canonical id."""

    def __init__(self) -> None:
        self._by_id: dict[str, RegisteredNode] = {}

    def register(
        self,
        fn: Callable[..., Any],
        *,
        name: Optional[str] = None,
        title: Optional[str] = None,
        outputs: Optional[list] = None,
        widgets: Optional[dict[str, Widget]] = None,
        module: Optional[str] = None,
        qualname: Optional[str] = None,
        replace: bool = False,
    ) -> RegisteredNode:
        """Register ``fn`` as a node type; return its :class:`RegisteredNode`.

        Raises:
            DuplicateNodeType: the id is already bound to a *different* callable
                and ``replace`` is false.
        """
        spec = node_spec(
            fn,
            name=name,
            title=title,
            outputs=outputs,
            widgets=widgets,
            module=module,
            qualname=qualname,
        )
        node_id = spec["id"]
        existing = self._by_id.get(node_id)
        if existing is not None and existing.fn is not fn and not replace:
            raise DuplicateNodeType(
                f"node type {node_id!r} is already registered to a different "
                f"callable; pass replace=True to override"
            )
        entry = RegisteredNode(id=node_id, name=spec["name"], fn=fn, spec=spec)
        self._by_id[node_id] = entry
        return entry

    def unregister_module(self, module: str) -> list[str]:
        """Drop every type whose spec ``module`` is ``module``; return the ids.

        Used before re-importing an edited authoring module: the reload runs the
        ``@node`` decorators again with *new* function objects, which would
        otherwise trip the duplicate-id guard.
        """
        removed = [nid for nid, e in self._by_id.items() if e.spec["module"] == module]
        for nid in removed:
            del self._by_id[nid]
        return removed

    def __contains__(self, node_id: str) -> bool:
        return node_id in self._by_id

    def get(self, node_id: str) -> RegisteredNode:
        try:
            return self._by_id[node_id]
        except KeyError:
            raise UnknownNodeType(f"node type {node_id!r} is not registered") from None

    def callable(self, node_id: str) -> Callable[..., Any]:
        return self.get(node_id).fn

    def spec(self, node_id: str) -> dict:
        return self.get(node_id).spec

    def specs(self) -> dict[str, dict]:
        """All specs keyed by id — the palette a UI renders from."""
        return {node_id: entry.spec for node_id, entry in self._by_id.items()}

    def ids(self) -> list[str]:
        return list(self._by_id)

    def by_short_name(self, name: str) -> RegisteredNode:
        """Look a type up by short name; error if it's ambiguous (UI helper)."""
        matches = [e for e in self._by_id.values() if e.name == name]
        if not matches:
            raise UnknownNodeType(f"no node type named {name!r}")
        if len(matches) > 1:
            ids = ", ".join(sorted(e.id for e in matches))
            raise UnknownNodeType(f"node name {name!r} is ambiguous — use a full id: {ids}")
        return matches[0]


# Process-wide default so ``run(graph)`` / ``to_python(graph)`` work without
# threading a registry through every call. Explicit registries are preferred for
# isolation (tests, multiple node packs).
DEFAULT_REGISTRY = NodeRegistry()
