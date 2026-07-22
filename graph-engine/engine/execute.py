"""``run(graph)`` — bind a graph, then execute it in dependency order.

``run`` first :func:`~engine.bind.bind`s the graph (all structural errors surface
there, before anything executes), then sweeps the bound nodes in topological
order. For each node it gathers inputs by reference — widget literals plus the
resolved value of each wired upstream socket — invokes the callable respecting
its parameter kinds (positional-only params are passed positionally), and stores
its outputs. A failure inside a node's code is wrapped in
:class:`~engine.errors.NodeExecutionError` carrying the node id, plus the
outputs/order of every node that ran to completion first (review 0005 #6) — a
caller can inspect what *did* execute instead of discarding it.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Optional, Union

from .bind import BoundGraph, BoundNode, bind
from .errors import GraphError, NodeExecutionError
from .graph import Graph
from .registry import NodeRegistry
from .spec import DEFAULT_OUTPUT, is_multi_output


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

    def value(self, node_id: str, socket: str = DEFAULT_OUTPUT) -> Any:
        """Convenience accessor for a single output socket's value."""
        return self.outputs[node_id][socket]


def _invoke(fn: Any, provided: dict[str, Any]) -> Any:
    """Call ``fn`` with ``provided`` values, honouring parameter kinds.

    Positional-only params are passed positionally (filling gaps with their
    defaults); everything else is passed by keyword.
    """
    params = list(inspect.signature(fn).parameters.values())
    pos_only = [p for p in params if p.kind == p.POSITIONAL_ONLY]

    args: list[Any] = []
    if pos_only:
        supplied = [i for i, p in enumerate(pos_only) if p.name in provided]
        last = max(supplied) if supplied else -1
        for i in range(last + 1):
            p = pos_only[i]
            args.append(provided[p.name] if p.name in provided else p.default)

    kwargs = {
        p.name: provided[p.name]
        for p in params
        if p.kind != p.POSITIONAL_ONLY and p.name in provided
    }
    return fn(*args, **kwargs)


def _store_outputs(bound: BoundNode, result: Any, outputs: dict[str, dict[str, Any]]) -> None:
    spec = bound.spec
    if is_multi_output(spec):
        if not isinstance(result, dict):
            raise GraphError(
                f"node {bound.id!r} ({bound.type}) declares outputs "
                f"{[o['name'] for o in spec['outputs']]} but returned "
                f"{type(result).__name__}, not a dict keyed by those names"
            )
        socket_values = {}
        for out in spec["outputs"]:
            if out["name"] not in result:
                raise GraphError(
                    f"node {bound.id!r} ({bound.type}) is missing declared output "
                    f"{out['name']!r} in its returned dict"
                )
            socket_values[out["name"]] = result[out["name"]]
        outputs[bound.id] = socket_values
    else:
        outputs[bound.id] = {spec["outputs"][0]["name"]: result}


def run(
    graph: Union[Graph, BoundGraph],
    registry: Optional[NodeRegistry] = None,
) -> ExecutionResult:
    """Execute ``graph`` (a :class:`Graph` or a pre-:func:`bind`ed graph)."""
    bound = graph if isinstance(graph, BoundGraph) else bind(graph, registry)

    outputs: dict[str, dict[str, Any]] = {}
    returns: dict[str, Any] = {}
    executed: list[str] = []

    for node in bound.nodes:
        provided = dict(node.literals)
        for param, (source, socket) in node.wired.items():
            provided[param] = outputs[source.id][socket]

        try:
            result = _invoke(node.entry.fn, provided)
        except Exception as exc:  # noqa: BLE001 - re-raised as NodeExecutionError
            # `outputs`/`executed` cover every node that finished before this
            # one failed — attach them so a caller isn't left with nothing.
            raise NodeExecutionError(node.id, node.type, exc, outputs=outputs, order=executed) from exc

        returns[node.id] = result
        _store_outputs(node, result, outputs)
        executed.append(node.id)

    return ExecutionResult(outputs=outputs, returns=returns, order=executed)
