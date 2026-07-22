"""``node_spec(fn)`` — turn a plain Python callable into a UI-agnostic node spec.

This is the introspection half of Nodezator's model, extracted so any front-end
(pygame today, ReactFlow later) can render a node from data alone:

* **parameters -> input sockets** (with a widget derived from type + default),
* **return annotation -> output socket(s)** (a list-of-dicts annotation means
  *multiple named outputs*, exactly like Nodezator),
* **docstring -> the node's on-canvas documentation**.

The result is a JSON-serialisable ``dict`` conforming to the frozen node-spec
schema in :mod:`engine.schema`. It carries no framework objects, so it survives
a round-trip through JSON untouched.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, Optional

# The single, default output-socket name used when a function has one plain
# return value (no list-of-dicts multi-output annotation).
DEFAULT_OUTPUT = "output"

# Python scalar types that render as an editable widget when a socket is left
# unconnected. Anything else (list, dict, custom classes) must be wired.
_WIDGET_BY_TYPE = {
    "float": {"kind": "number", "subtype": "float"},
    "int": {"kind": "number", "subtype": "int"},
    "str": {"kind": "text"},
    "bool": {"kind": "checkbox"},
}

_JSON_SCALARS = (str, int, float, bool, type(None))


def _type_name(annotation: Any) -> Optional[str]:
    """Best-effort, JSON-safe name for a type annotation.

    Handles real types (``float`` -> ``"float"``), string forward-refs
    (``"si.Physical"`` -> ``"si.Physical"``) and the ``empty`` sentinels.
    """
    if annotation is inspect.Parameter.empty or annotation is inspect.Signature.empty:
        return None
    if isinstance(annotation, str):
        return annotation
    if isinstance(annotation, type):
        return annotation.__name__
    return getattr(annotation, "__name__", None) or str(annotation)


def _jsonify_default(value: Any) -> tuple[Any, Optional[str]]:
    """Split a default into (json_value, repr_fallback).

    JSON scalars pass through as-is; anything else is represented by its
    ``repr()`` so the spec stays serialisable without losing information.
    """
    if isinstance(value, _JSON_SCALARS):
        return value, None
    return None, repr(value)


def _widget_for(type_name: Optional[str]) -> Optional[dict]:
    if type_name is None:
        return None
    return _WIDGET_BY_TYPE.get(type_name)


def _input_spec(param: inspect.Parameter) -> dict:
    type_name = _type_name(param.annotation)
    required = param.default is inspect.Parameter.empty
    default, default_repr = (None, None)
    if not required:
        default, default_repr = _jsonify_default(param.default)

    entry: dict[str, Any] = {
        "name": param.name,
        "type": type_name or "Any",
        "required": required,
        "default": default,
        "widget": _widget_for(type_name),
    }
    if default_repr is not None:
        entry["defaultRepr"] = default_repr
    return entry


def _outputs_from_return(return_annotation: Any) -> list[dict]:
    """Derive output sockets from a return annotation.

    A ``list`` annotation (list-of-dicts, each with a ``name``) declares
    multiple named outputs — Nodezator's multi-output convention. Anything else
    is a single output socket named :data:`DEFAULT_OUTPUT`.
    """
    if isinstance(return_annotation, list):
        outputs = []
        for item in return_annotation:
            if not isinstance(item, dict) or "name" not in item:
                raise ValueError(
                    "multi-output return annotation must be a list of dicts "
                    "each carrying a 'name' key"
                )
            item_type = _type_name(item["type"]) if "type" in item else None
            outputs.append({"name": item["name"], "type": item_type or "Any"})
        return outputs
    return [{"name": DEFAULT_OUTPUT, "type": _type_name(return_annotation) or "Any"}]


def node_spec(
    fn: Callable[..., Any],
    *,
    name: Optional[str] = None,
    title: Optional[str] = None,
    outputs: Optional[list] = None,
    imports: Optional[dict] = None,
) -> dict:
    """Introspect ``fn`` into a node spec (see module docstring).

    Args:
        fn: the callable a node wraps (Nodezator's ``main_callable``).
        name: registry key for the node type; defaults to ``fn.__name__``.
        title: human label; defaults to ``name``.
        outputs: explicit output sockets, overriding return-annotation
            inference. Use for functions that return a ``dict`` but declare a
            plain ``-> dict`` (e.g. ``render_stress_check``): pass
            ``["latex", "utilisation", "summary"]`` or a list of
            ``{"name": ..., "type": ...}`` dicts to expose the keys as sockets.
        imports: ``{"stdlib": str|None, "thirdParty": str|None}`` import lines
            injected into exported Python so the generated script resolves the
            callable (Nodezator's ``third_party_import_text``).

    Returns:
        A JSON-serialisable node-spec ``dict`` (frozen schema in
        :mod:`engine.schema`).
    """
    signature = inspect.signature(fn)
    resolved_name = name or fn.__name__

    inputs = [
        _input_spec(param)
        for param in signature.parameters.values()
        if param.kind
        in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    ]

    if outputs is not None:
        output_specs = [
            {"name": o, "type": "Any"}
            if isinstance(o, str)
            else {"name": o["name"], "type": _type_name(o.get("type")) if "type" in o else "Any"}
            for o in outputs
        ]
    else:
        output_specs = _outputs_from_return(signature.return_annotation)

    imports = imports or {}
    return {
        "name": resolved_name,
        "title": title or resolved_name,
        "callName": fn.__name__,
        "doc": inspect.getdoc(fn) or "",
        "inputs": inputs,
        "outputs": output_specs,
        "imports": {
            "stdlib": imports.get("stdlib"),
            "thirdParty": imports.get("thirdParty"),
        },
    }


def is_multi_output(spec: dict) -> bool:
    """True when a node has >1 output socket, i.e. it returns a keyed dict."""
    return len(spec["outputs"]) > 1
