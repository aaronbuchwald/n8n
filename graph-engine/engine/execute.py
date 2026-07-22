"""``run(graph)`` — execute a graph by a topological sweep.

For each node in dependency order we gather its inputs (widget literals for
unconnected sockets, upstream values for connected ones), call the node's
callable, and store its outputs. Multi-output nodes return a ``dict`` keyed by
their socket names; single-output nodes contribute their whole return value on
the ``output`` socket. Parents always resolve before children, so every input
is available when a node runs — the same guarantee Nodezator's lazy retry gives.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .errors import GraphError
from .graph import Graph
from .ordering import topological_order
from .registry import DEFAULT_REGISTRY, NodeRegistry
from .spec import is_multi_output


@dataclass
class ExecutionResult:
    """Outcome of :func:`run`.

    Attributes:
        outputs: ``node_id -> {socket_name -> value}`` — every output socket.
        returns: ``node_id -> raw return value`` of each callable.
        order: the topological order the nodes ran in.
    """

    outputs: dict[str, dict[str, Any]]
    returns: dict[str, Any]
    order: list[str]

    def value(self, node_id: str, socket: str = "output") -> Any:
        """Convenience accessor for a single output socket's value."""
        return self.outputs[node_id][socket]


def run(graph: Graph, registry: Optional[NodeRegistry] = None) -> ExecutionResult:
    """Execute ``graph`` and return an :class:`ExecutionResult`.

    Args:
        graph: the graph to run.
        registry: node-type registry; defaults to
            :data:`engine.registry.DEFAULT_REGISTRY`.
    """
    registry = registry or DEFAULT_REGISTRY
    order = topological_order(graph)

    outputs: dict[str, dict[str, Any]] = {}
    returns: dict[str, Any] = {}

    for node_id in order:
        node = graph.node(node_id)
        entry = registry.get(node.type)
        spec = entry.spec

        # Start from widget literals, then let connected edges override.
        kwargs: dict[str, Any] = dict(node.inputs)
        for edge in graph.incoming(node_id):
            source_outputs = outputs[edge.source] # doesn't this mean that we will always take the source outputs by stringified key
            # how would this deal with collisions? it seems like real instances that link a full node type directly would be much better.
            if edge.source_output not in source_outputs: # this type of error should be detectable as missing before running, not during
                raise GraphError(
                    f"node {node_id!r} input {edge.target_input!r} is wired to "
                    f"{edge.source!r}.{edge.source_output!r}, which is not an "
                    f"output of that node"
                )
            kwargs[edge.target_input] = source_outputs[edge.source_output]

        result = entry.fn(**kwargs) # do we only support kwargs and not args here? That seems wrong.
        returns[node_id] = result

        if is_multi_output(spec):
            if not isinstance(result, dict):
                raise GraphError(
                    f"node {node_id!r} ({node.type}) declares multiple outputs "
                    f"but returned {type(result).__name__}, not a dict"
                )
            outputs[node_id] = { # it seems you can only read an output via one edge.source name above
                # but you can't read a nested property of the output, which is not great. This makes it
                # unclear to me how if you are returning multiple outputs, you'd connect just one of those
                # outputs to a successive node?
                out["name"]: result[out["name"]] for out in spec["outputs"]
            }
        else:
            outputs[node_id] = {spec["outputs"][0]["name"]: result}

    return ExecutionResult(outputs=outputs, returns=returns, order=order)
