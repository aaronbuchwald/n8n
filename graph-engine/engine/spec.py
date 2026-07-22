"""``node_spec(fn)`` — turn a plain Python callable into a UI-agnostic node spec.

This is the introspection half of Nodezator's model, extracted so any front-end
(pygame today, ReactFlow later) can render a node from data alone:

* **parameters -> input sockets** (with a widget derived from type + default,
  and the parameter *kind* recorded so positional-only params still work),
* **return value -> output socket(s)** — one ``result`` socket by default; pass
  ``outputs=[...]`` to declare several named sockets (the function then returns a
  dict keyed by those names),
* **docstring -> the node's on-canvas documentation**,
* **module + qualname -> a structured, collision-proof identity** (two functions
  named ``total`` from different packages get distinct ids).

The result is a JSON-serialisable ``dict`` conforming to the node-spec schema in
:mod:`engine.schema`.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, Optional

from .errors import EngineError

# Default output-socket name when a function has one plain return value.
DEFAULT_OUTPUT = "result"

# Python scalar types that render as an editable widget when a socket is left
# unconnected. Anything else (list, dict, custom classes) must be wired.
_WIDGET_BY_TYPE = {
    "float": {"kind": "number", "subtype": "float"},
    "int": {"kind": "number", "subtype": "int"},
    "str": {"kind": "text"},
    "bool": {"kind": "checkbox"},
}

# Parameter kinds we expose as input sockets, mapped to their spec label.
_KIND_LABEL = {
    inspect.Parameter.POSITIONAL_ONLY: "positionalOnly",
    inspect.Parameter.POSITIONAL_OR_KEYWORD: "positionalOrKeyword",
    inspect.Parameter.KEYWORD_ONLY: "keywordOnly",
}

_JSON_SCALARS = (str, int, float, bool, type(None))


def _type_name(annotation: Any) -> Optional[str]:
    """Best-effort, JSON-safe name for a type annotation."""
    if annotation is inspect.Parameter.empty or annotation is inspect.Signature.empty:
        return None
    if isinstance(annotation, str):
        return annotation
    if isinstance(annotation, type):
        return annotation.__name__
    return getattr(annotation, "__name__", None) or str(annotation)


def _jsonify_default(value: Any) -> tuple[Any, Optional[str]]:
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
        "kind": _KIND_LABEL[param.kind],
        "required": required,
        "default": default,
        "widget": _widget_for(type_name),
    }
    if default_repr is not None:
        entry["defaultRepr"] = default_repr
    return entry


def _output_specs(outputs: Optional[list], return_annotation: Any) -> list[dict]:
    """Derive output sockets.

    With ``outputs`` given: those named sockets (a multi-socket node returns a
    dict keyed by the names). Without: a single :data:`DEFAULT_OUTPUT` socket
    carrying the whole return value — no special-casing of dict returns, and no
    magic from the return annotation.
    """
    if outputs is not None:
        result = []
        for item in outputs:
            if isinstance(item, str):
                result.append({"name": item, "type": "Any"})
            else:
                result.append(
                    {"name": item["name"], "type": _type_name(item.get("type")) or "Any"}
                )
        if not result:
            raise EngineError("outputs=[] is not valid; omit it for a single output")
        return result
    return [{"name": DEFAULT_OUTPUT, "type": _type_name(return_annotation) or "Any"}]


def node_spec(
    fn: Callable[..., Any],
    *,
    name: Optional[str] = None,
    title: Optional[str] = None,
    outputs: Optional[list] = None,
    module: Optional[str] = None,
    qualname: Optional[str] = None,
) -> dict:
    """Introspect ``fn`` into a node spec (see module docstring).

    Args:
        fn: the callable a node wraps.
        name: short display name; defaults to ``fn.__name__``.
        title: human label; defaults to ``name``.
        outputs: explicit output sockets (names or ``{"name","type"}`` dicts);
            >1 makes a multi-output node whose callable returns a keyed dict.
        module / qualname: override the identity (defaults to ``fn.__module__`` /
            ``fn.__qualname__``); together they form the collision-proof id.

    Raises:
        EngineError: the callable uses ``*args``/``**kwargs`` (not addressable as
            named sockets).
    """
    signature = inspect.signature(fn)
    short_name = name or fn.__name__
    module = module or fn.__module__
    qualname = qualname or fn.__qualname__

    inputs = []
    for param in signature.parameters.values():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            raise EngineError(
                f"{short_name!r} uses *args/**kwargs, which cannot be named "
                f"input sockets; wrap it in a fixed-signature function"
            )
        inputs.append(_input_spec(param))

    return {
        "id": f"{module}.{qualname}",
        "name": short_name,
        "title": title or short_name,
        "module": module,
        "qualname": qualname,
        "doc": inspect.getdoc(fn) or "",
        "inputs": inputs,
        "outputs": _output_specs(outputs, signature.return_annotation),
    }


def is_multi_output(spec: dict) -> bool:
    """True when a node has >1 output socket (its callable returns a keyed dict)."""
    return len(spec["outputs"]) > 1
