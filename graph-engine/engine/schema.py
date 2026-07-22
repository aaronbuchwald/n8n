"""The contract: JSON Schemas for node specs and graphs, plus lenient validation.

``engine/schema.py`` is the **source of truth** for the node-spec / graph shapes.
The schemas are additive-tolerant on purpose (``additionalProperties: true``):
adding an optional field is a MINOR bump, not a breaking change, and readers
ignore unknown fields — the forwards-compatibility story. Formal migration
machinery is deferred (see docs/adr/0001-*.md) until backwards-compat matters.

Validation here is dependency-free and targeted (clear messages for the fields
that matter), and deliberately lenient: it never rejects extra keys.
"""

from __future__ import annotations

from typing import Any

from .errors import SchemaError
from .version import SCHEMA_VERSION

# --------------------------------------------------------------------------
# Schema documents (regenerated to JSON on demand: freeze_schemas.py --contract)
# --------------------------------------------------------------------------

NODE_SPEC_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://n8n.io/graph-engine/node-spec.schema.json",
    "title": "NodeSpec",
    "description": "A UI-agnostic description of one node type, derived from a Python callable.",
    "type": "object",
    "required": ["id", "name", "title", "module", "qualname", "doc", "inputs", "outputs"],
    "additionalProperties": True,
    "properties": {
        "id": {"type": "string", "description": "Canonical id: '<module>.<qualname>' (collision-proof)."},
        "name": {"type": "string", "description": "Short display name."},
        "title": {"type": "string", "description": "Human-facing label."},
        "module": {"type": "string", "description": "Defining module — used to import the callable."},
        "qualname": {"type": "string", "description": "Qualified name of the callable within its module."},
        "doc": {"type": "string", "description": "Docstring — the node's on-canvas documentation."},
        "inputs": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "type", "kind", "required", "default", "widget"],
                "additionalProperties": True,
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string", "description": "Annotation name (e.g. 'float')."},
                    "kind": {"enum": ["positionalOnly", "positionalOrKeyword", "keywordOnly"]},
                    "required": {"type": "boolean", "description": "True when the parameter has no default."},
                    "default": {"type": ["string", "number", "boolean", "null"]},
                    "defaultRepr": {"type": "string", "description": "repr() of a non-JSON default; present only then."},
                    "widget": {
                        "oneOf": [
                            {"type": "null"},
                            {
                                "type": "object",
                                "required": ["kind"],
                                "additionalProperties": True,
                                "properties": {
                                    "kind": {"type": "string", "description": "Open vocabulary; core: number|text|checkbox."},
                                    "subtype": {"type": "string"},
                                },
                            },
                        ]
                    },
                },
            },
        },
        "outputs": {
            "type": "array",
            "minItems": 1,
            "description": "One 'result' socket by default; several when declared (callable returns a keyed dict).",
            "items": {
                "type": "object",
                "required": ["name", "type"],
                "additionalProperties": True,
                "properties": {"name": {"type": "string"}, "type": {"type": "string"}},
            },
        },
    },
}

GRAPH_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://n8n.io/graph-engine/graph.schema.json",
    "title": "Graph",
    "description": "A saved graph: node instances, output->input connections, and the result socket.",
    "type": "object",
    "required": ["version", "nodes", "edges"],
    "additionalProperties": True,
    "properties": {
        "version": {"type": "string", "description": f"Schema version (current: {SCHEMA_VERSION})."},
        "nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "type"],
                "additionalProperties": True,
                "properties": {
                    "id": {"type": "string", "description": "Unique instance id within the graph."},
                    "type": {"type": "string", "description": "Node-spec id in the registry."},
                    "inputs": {"type": "object", "description": "Literal widget values for unconnected inputs."},
                    "position": {
                        "oneOf": [
                            {"type": "null"},
                            {"type": "object", "required": ["x", "y"],
                             "properties": {"x": {"type": "number"}, "y": {"type": "number"}}},
                        ]
                    },
                },
            },
        },
        "edges": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["source", "sourceOutput", "target", "targetInput"],
                "additionalProperties": True,
                "properties": {
                    "source": {"type": "string"},
                    "sourceOutput": {"type": "string"},
                    "target": {"type": "string"},
                    "targetInput": {"type": "string"},
                },
            },
        },
        "output": {
            "description": "Which socket is the graph's result (UI display), or null.",
            "oneOf": [
                {"type": "null"},
                {"type": "object", "required": ["node", "socket"],
                 "properties": {"node": {"type": "string"}, "socket": {"type": "string"}}},
            ],
        },
    },
}


# --------------------------------------------------------------------------
# Lightweight, dependency-free, lenient validation
# --------------------------------------------------------------------------


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SchemaError(message)


def validate_node_spec(spec: Any) -> dict:
    """Validate a node-spec dict; return it. Unknown keys are tolerated."""
    _require(isinstance(spec, dict), "node spec must be an object")
    for key in ("id", "name", "title", "module", "qualname", "doc", "inputs", "outputs"):
        _require(key in spec, f"node spec missing required key: {key!r}")
    _require(isinstance(spec["inputs"], list), "node spec 'inputs' must be a list")
    for inp in spec["inputs"]:
        for key in ("name", "type", "kind", "required", "default", "widget"):
            _require(key in inp, f"input {inp.get('name')!r} missing key {key!r}")
    _require(isinstance(spec["outputs"], list) and spec["outputs"], "node spec needs >=1 output")
    for out in spec["outputs"]:
        _require("name" in out and "type" in out, "each output needs 'name' and 'type'")
    return spec


def validate_graph(graph: Any) -> dict:
    """Validate a graph dict (shape + edge referential integrity); return it.

    Unknown keys are tolerated. Node-type existence and cycles are checked by
    :func:`engine.bind.bind`, which has the registry context to report them well.
    """
    _require(isinstance(graph, dict), "graph must be an object")
    for key in ("version", "nodes", "edges"):
        _require(key in graph, f"graph missing required key: {key!r}")
    _require(isinstance(graph["nodes"], list), "graph 'nodes' must be a list")
    _require(isinstance(graph["edges"], list), "graph 'edges' must be a list")

    ids: set[str] = set()
    for node in graph["nodes"]:
        _require("id" in node and "type" in node, "each node needs 'id' and 'type'")
        _require(node["id"] not in ids, f"duplicate node id: {node['id']!r}")
        ids.add(node["id"])

    for edge in graph["edges"]:
        for key in ("source", "sourceOutput", "target", "targetInput"):
            _require(key in edge, f"edge missing key {key!r}")
        _require(edge["source"] in ids, f"edge source {edge['source']!r} is not a node id")
        _require(edge["target"] in ids, f"edge target {edge['target']!r} is not a node id")

    output = graph.get("output")
    if output is not None:
        _require("node" in output and "socket" in output, "graph 'output' needs 'node' and 'socket'")
        _require(output["node"] in ids, f"graph output node {output['node']!r} is not a node id")
    return graph
