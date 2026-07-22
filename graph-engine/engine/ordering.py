"""Dependency ordering shared by the executor and the Python emitter.

Nodezator resolves the graph with a lazy sweep: retry each node until its
parents are ready (a ``WaitingParentException`` defers it). That converges to a
topological order, so the headless core computes the order directly with Kahn's
algorithm — equivalent, but deterministic and O(V+E) with explicit cycle
detection.
"""

from __future__ import annotations

from .errors import CycleError, GraphError
from .graph import Graph


def topological_order(graph: Graph) -> list[str]:
    """Return node ids so every source precedes its targets.

    Raises:
        GraphError: an edge references a node id that doesn't exist.
        CycleError: the graph contains a cycle.
    """
    ids = [n.id for n in graph.nodes]
    id_set = set(ids)

    for edge in graph.edges:
        if edge.source not in id_set or edge.target not in id_set:
            raise GraphError(
                f"edge {edge.source!r}->{edge.target!r} references an unknown node"
            )

    # Collapse parallel edges (e.g. several unpacked fields feeding one node)
    # to a single dependency so they don't inflate indegree.
    # TODO: human review and ensure there's sufficient testing for topological sort
    # ideally over a generic type, so that it's not directly linked to the engine.
    unique_pairs = {(e.source, e.target) for e in graph.edges}
    indegree = {nid: 0 for nid in ids}
    successors: dict[str, list[str]] = {nid: [] for nid in ids}
    for source, target in unique_pairs:
        indegree[target] += 1
        successors[source].append(target)

    # Seed with indegree-0 nodes in declaration order for stable output.
    queue = [nid for nid in ids if indegree[nid] == 0]
    order: list[str] = []
    while queue:
        current = queue.pop(0)
        order.append(current)
        for succ in successors[current]:
            indegree[succ] -= 1
            if indegree[succ] == 0:
                queue.append(succ)

    if len(order) != len(ids):
        stuck = sorted(set(ids) - set(order))
        raise CycleError(f"graph has a cycle involving: {', '.join(stuck)}")

    return order
