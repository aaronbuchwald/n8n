"""The **frozen contract**: JSON Schemas for node specs and graphs.

Every later UI (FastAPI endpoints, the ReactFlow front-end, a VS Code webview)
depends on these two shapes, so they are versioned data, not code. The schema
documents below are JSON Schema draft 2020-12 and are also written to
``engine/schemas/*.json`` for out-of-band review and tooling.

Validation here is dependency-free and targeted (clear messages for the fields
that matter) rather than a full JSON-Schema engine — the schema *documents* are
the authoritative contract; :func:`validate_node_spec` / :func:`validate_graph`
are a pragmatic guard.
"""

from __future__ import annotations

from typing import Any

from .errors import SchemaError
from .graph import SCHEMA_VERSION

# --------------------------------------------------------------------------
# Frozen JSON Schema documents
# --------------------------------------------------------------------------

# given this schema, don't we lose track of the body of the functions and only have the inputs/outputs?
# if in the UI we are actually going to preserve the ability to run a python entrypoint in a node directly
# then we may want the ability to support inter-process communication with standard serialization format (support cross-language boudnaries)
# and include the full code body annotated as "python able to run in env X ie. docker image with specific uv defined env"
NODE_SPEC_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://n8n.io/nodezator-engine/node-spec.schema.json",
    "title": "NodeSpec",
    "description": "A UI-agnostic description of one node type, derived from a Python callable.",
    "type": "object",
    "required": ["name", "title", "callName", "doc", "inputs", "outputs", "imports"],
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string", "description": "Registry key / node-type id."},
        "title": {"type": "string", "description": "Human-facing label."},
        "callName": {
            "type": "string",
            "description": "The callable's __name__, used verbatim in exported Python.",
        },
        "doc": {"type": "string", "description": "Docstring — the node's on-canvas documentation."},
        "inputs": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "type", "required", "default", "widget"],
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string", "description": "Annotation name (e.g. 'float', 'si.Physical')."},
                    "required": {"type": "boolean", "description": "True when the parameter has no default."},
                    "default": {
                        "description": "Default widget value if a JSON scalar, else null (see defaultRepr).",
                        "type": ["string", "number", "boolean", "null"],
                    },
                    "defaultRepr": {
                        "type": "string",
                        "description": "repr() of a non-JSON-scalar default; present only then.",
                    },
                    "widget": {
                        "description": "Editable control for an unconnected input, or null (must be wired).",
                        "oneOf": [
                            {"type": "null"},
                            {
                                "type": "object",
                                "required": ["kind"],
                                "additionalProperties": False,
                                "properties": {
                                    "kind": {"enum": ["number", "text", "checkbox"]},
                                    "subtype": {"enum": ["int", "float"]},
                                },
                            },
                        ],
                    },
                },
            },
        },
        "outputs": {
            "type": "array",
            "minItems": 1,
            "description": "One socket for a plain return; many for a keyed-dict / multi-output node.",
            "items": {
                "type": "object",
                "required": ["name", "type"],
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string"},
                },
            },
        },
        "imports": {
            "type": "object",
            "required": ["stdlib", "thirdParty"],
            "additionalProperties": False,
            "description": "Import lines injected into exported Python so it resolves the callable.",
            "properties": {
                "stdlib": {"type": ["string", "null"]},
                "thirdParty": {"type": ["string", "null"]},
            },
        },
    },
}

GRAPH_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://n8n.io/nodezator-engine/graph.schema.json",
    "title": "Graph",
    "description": "A saved graph: node instances plus output->input connections.",
    "type": "object",
    "required": ["version", "nodes", "edges"],
    "additionalProperties": False,
    "properties": {
        "version": {"type": "string", "const": SCHEMA_VERSION},
        "nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "type"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "description": "Unique instance id within the graph."},
                    "type": {"type": "string", "description": "Node-spec name in the registry."},
                    "inputs": {
                        "type": "object",
                        "description": "Literal widget values for unconnected inputs (param -> value).",
                    },
                    "position": {
                        "description": "UI-only canvas coordinates; ignored by run/export.",
                        "oneOf": [
                            {"type": "null"},
                            {
                                "type": "object",
                                "required": ["x", "y"],
                                "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
                            },
                        ],
                    },
                },
            },
        },
        "edges": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["source", "sourceOutput", "target", "targetInput"],
                "additionalProperties": False,
                "properties": {
                    "source": {"type": "string", "description": "Source node id."},
                    "sourceOutput": {"type": "string", "description": "Source output-socket name."},
                    "target": {"type": "string", "description": "Target node id."},
                    "targetInput": {"type": "string", "description": "Target input (parameter) name."},
                },
            },
        },
    },
}


# --------------------------------------------------------------------------
# Lightweight, dependency-free validation
# --------------------------------------------------------------------------


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SchemaError(message)


def validate_node_spec(spec: Any) -> dict:
    """Validate a node-spec dict against the frozen contract; return it."""
    _require(isinstance(spec, dict), "node spec must be an object")
    for key in ("name", "title", "callName", "doc", "inputs", "outputs", "imports"):
        _require(key in spec, f"node spec missing required key: {key!r}")
    _require(isinstance(spec["inputs"], list), "node spec 'inputs' must be a list")
    for inp in spec["inputs"]:
        for key in ("name", "type", "required", "default", "widget"):
            _require(key in inp, f"input {inp.get('name')!r} missing key {key!r}")
    _require(isinstance(spec["outputs"], list) and spec["outputs"], "node spec needs >=1 output")
    for out in spec["outputs"]:
        _require("name" in out and "type" in out, "each output needs 'name' and 'type'")
    _require(
        isinstance(spec["imports"], dict)
        and "stdlib" in spec["imports"]
        and "thirdParty" in spec["imports"],
        "node spec 'imports' must have 'stdlib' and 'thirdParty'",
    )
    return spec


def validate_graph(graph: Any) -> dict:
    """Validate a graph dict against the frozen contract; return it.

    Structural checks only (shape + referential integrity of edges). Node-type
    existence and cycles are checked by the registry/executor, which have the
    context to report them well.
    """
    _require(isinstance(graph, dict), "graph must be an object")
    for key in ("version", "nodes", "edges"):
        _require(key in graph, f"graph missing required key: {key!r}")
    _require(graph["version"] == SCHEMA_VERSION, f"graph version must be {SCHEMA_VERSION!r}")
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
    return graph
