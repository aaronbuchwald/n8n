"""Topological ordering — a generic Kahn's algorithm, plus a graph wrapper.

The core :func:`topological_sort` is decoupled from the engine: it works over any
hashable node ids and ``(source, target)`` dependency pairs, so it's trivially
property-testable in isolation. :func:`topological_order` is the thin
:class:`~engine.graph.Graph` adapter.
"""

from __future__ import annotations

from collections import deque
from typing import Hashable, Iterable, TypeVar

from .errors import CycleError, GraphError
from .graph import Graph

T = TypeVar("T", bound=Hashable)


def topological_sort(nodes: Iterable[T], edges: Iterable[tuple[T, T]]) -> list[T]:
    """Return ``nodes`` so every source precedes its target (stable order).

    Parallel edges between the same pair collapse to one dependency. Ordering is
    deterministic: indegree-0 nodes are emitted in ``nodes`` iteration order,
    which keeps downstream output (e.g. generated Python) byte-stable.

    Raises:
        GraphError: an edge references an id not in ``nodes``.
        CycleError: the input contains a cycle.
    """
    ids = list(nodes)
    id_set = set(ids)

    indegree: dict[T, int] = {nid: 0 for nid in ids}
    successors: dict[T, list[T]] = {nid: [] for nid in ids}

    seen_pairs: set[tuple[T, T]] = set()
    for source, target in edges:
        if source not in id_set or target not in id_set:
            raise GraphError(f"dependency {source!r}->{target!r} references an unknown node")
        if source == target:
            raise CycleError(f"self-dependency on {source!r}")
        if (source, target) in seen_pairs:
            continue
        seen_pairs.add((source, target))
        indegree[target] += 1
        successors[source].append(target)

    queue = deque(nid for nid in ids if indegree[nid] == 0)
    order: list[T] = []
    while queue:
        current = queue.popleft()
        order.append(current)
        for succ in successors[current]:
            indegree[succ] -= 1
            if indegree[succ] == 0:
                queue.append(succ)

    if len(order) != len(ids):
        stuck = sorted(str(nid) for nid in id_set - set(order))
        raise CycleError(f"graph has a cycle involving: {', '.join(stuck)}")
    return order


def topological_order(graph: Graph) -> list[str]:
    """Topologically order a :class:`~engine.graph.Graph`'s node ids."""
    return topological_sort(
        (n.id for n in graph.nodes),
        ((e.source, e.target) for e in graph.edges),
    )
