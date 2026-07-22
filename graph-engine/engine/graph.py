"""The ``Graph`` data model — nodes + edges as plain, serialisable data.

A graph is *just data*: which node types are placed, their positions, the widget
values on unconnected inputs, the output->input connections between them, and
which socket is the graph's result. Nothing here executes or validates; that
keeps the model portable across UIs and cheap to (de)serialise. Turning this
string-keyed data into a validated, reference-linked runnable form is the job of
:func:`engine.bind.bind` — the one place ids are resolved.

Two ways to build one:

* **In code** with the fluent builder::

      g = Graph()
      g.add("csv", "pkg.read_csv", inputs={"path": "members.csv"})
      g.add("pick", "pkg.select", inputs={"index": 0})
      g.connect("csv", "result", "pick", "rows")

* **From JSON** with :meth:`Graph.from_dict` / :meth:`Graph.from_json`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from .version import SCHEMA_VERSION

__all__ = ["Node", "Edge", "Graph", "SCHEMA_VERSION"]


@dataclass
class Node:
    """A placed node instance.

    ``type`` is the registry id of the node spec. ``inputs`` holds literal widget
    values for inputs left unconnected; connected inputs take their value from
    the incoming edge at run time. ``position`` is UI-only and never affects
    execution or export.
    """

    id: str
    type: str
    inputs: dict[str, Any] = field(default_factory=dict)
    position: Optional[dict[str, float]] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "inputs": dict(self.inputs),
            "position": self.position,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Node":
        return cls(
            id=data["id"],
            type=data["type"],
            inputs=dict(data.get("inputs") or {}),
            position=data.get("position"),
        )


@dataclass
class Edge:
    """A directed connection: ``source.source_output -> target.target_input``.

    Endpoints are string ids/socket-names — the portable wire form. They are
    resolved to object references exactly once, in :func:`engine.bind.bind`.
    """

    source: str
    source_output: str
    target: str
    target_input: str

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "sourceOutput": self.source_output,
            "target": self.target,
            "targetInput": self.target_input,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Edge":
        return cls(
            source=data["source"],
            source_output=data.get("sourceOutput", "result"),
            target=data["target"],
            target_input=data["targetInput"],
        )


@dataclass
class Graph:
    """Nodes + edges (+ the result socket), with (de)serialisation and an id map.

    ``output`` names the socket a UI should display as the graph's result:
    ``{"node": id, "socket": name}`` (or ``None``). It is set by the tracing
    layer and preserved through JSON — unlike the old dynamically-injected
    attribute, it survives a round-trip.
    """

    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    output: Optional[dict[str, str]] = None
    version: str = SCHEMA_VERSION
    _by_id: dict[str, Node] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        self._by_id = {}
        for n in self.nodes:
            if n.id in self._by_id:
                raise ValueError(f"duplicate node id: {n.id!r}")
            self._by_id[n.id] = n

    # -- fluent building -------------------------------------------------
    def add(
        self,
        id: str,
        type: str,
        *,
        inputs: Optional[dict[str, Any]] = None,
        position: Optional[dict[str, float]] = None,
    ) -> "Graph":
        """Add a node and return ``self`` for chaining."""
        if id in self._by_id:
            raise ValueError(f"duplicate node id: {id!r}")
        node = Node(id=id, type=type, inputs=dict(inputs or {}), position=position)
        self.nodes.append(node)
        self._by_id[id] = node
        return self

    def connect(self, source: str, source_output: str, target: str, target_input: str) -> "Graph":
        """Add an edge and return ``self`` for chaining.

        Endpoints are not checked here — that is deliberate. A graph stays a dumb
        data bag (forward references while building are legal); :func:`bind`
        validates every endpoint once, up front, with precise errors.
        """
        self.edges.append(
            Edge(source=source, source_output=source_output, target=target, target_input=target_input)
        )
        return self

    # -- queries (O(1) id lookup) ---------------------------------------
    def node(self, node_id: str) -> Node:
        try:
            return self._by_id[node_id]
        except KeyError:
            raise KeyError(f"no node with id {node_id!r}") from None

    def incoming(self, node_id: str) -> list[Edge]:
        """Edges terminating on ``node_id`` (its connected inputs)."""
        return [e for e in self.edges if e.target == node_id]

    # -- serialisation ---------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "output": self.output,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Graph":
        return cls(
            nodes=[Node.from_dict(n) for n in data.get("nodes", [])],
            edges=[Edge.from_dict(e) for e in data.get("edges", [])],
            output=data.get("output"),
            version=data.get("version", SCHEMA_VERSION),
        )

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_json(cls, text: str) -> "Graph":
        return cls.from_dict(json.loads(text))
