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
import json
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .errors import EngineError, UserError

# Default output-socket name when a function has one plain return value.
DEFAULT_OUTPUT = "result"


@dataclass(frozen=True)
class DerivedInputs:
    """Extra input sockets derived from one literal parameter's value (ADR 0007).

    A node type may declare that some of its input sockets are not fixed by its
    Python signature but computed from the *value* of one designated literal
    parameter (e.g. the equation text a handcalc node typesets). The engine owns
    exactly one derivation seam; the effective inputs of an instance are the
    static signature sockets **plus** ``derive(literals[param])``.

    Args:
        param: the static input whose *value* drives derivation (e.g. ``"lines"``).
            Must name a declared parameter; :func:`engine.bind.bind` requires it to
            be a literal, never wired (ADR 0007 D2).
        derive: a **pure** function ``value -> ordered list of input-spec entries``
            (the same dict shape as ``spec["inputs"]`` plus ``"derived": True``).
            Contract: deterministic, no I/O, never ``exec``/``eval`` the value,
            cheap (it runs at bind time and per keystroke via the derive endpoint).
            Raises :class:`~engine.errors.UserError` on an invalid value.
    """

    param: str
    derive: Callable[[Any], list[dict]]


def effective_inputs(
    spec: dict, dynamic: Optional[DerivedInputs], literals: dict
) -> list[dict]:
    """``spec["inputs"]`` + the derived entries from ``literals[dynamic.param]``.

    For a non-dynamic node this is just the static inputs. For a dynamic node the
    deriver runs against the current value of the deriving parameter (falling back
    to that parameter's static default when the instance leaves it unset). Derived
    entries are appended in the order the deriver returned them and are rejected if
    any name collides with a static input. The deriver may raise
    :class:`~engine.errors.UserError`; callers (bind, the derive endpoint) surface
    it as their own structural error.
    """
    inputs = list(spec["inputs"])
    if dynamic is None:
        return inputs

    if dynamic.param in literals:
        value = literals[dynamic.param]
    else:
        static = next((i for i in inputs if i["name"] == dynamic.param), None)
        value = static["default"] if static is not None else None

    derived = dynamic.derive(value)
    static_names = {i["name"] for i in inputs}
    for entry in derived:
        if entry["name"] in static_names:
            raise UserError(
                f"derived socket {entry['name']!r} collides with a static input "
                f"of the node — rename the symbol"
            )
    return inputs + list(derived)


class Widget:
    """A declarative editing-widget contract for one input (ADR 0005 A-D2).

    A ``Widget`` declares only a *contract* — a registry ``kind`` the UI resolves
    to an editor component, plus JSON-serialisable ``config`` that is opaque to
    the engine. No HTML, no callbacks; a headless or non-React front-end is free
    to ignore or reinterpret it. Serialised into the input spec's existing
    ``widget`` field as ``{"kind": ..., "config"?: {...}}`` (additive, A-D3).

    Args:
        kind: registry key the UI resolves to an editor component (open
            vocabulary; core kinds: ``number``/``text``/``checkbox``).
        **config: JSON-serialisable options passed through to that editor. The
            ``json.dumps`` guard fails at import time — not save time — if a
            caller passes something unserialisable.
    """

    __slots__ = ("kind", "config")

    def __init__(self, kind: str, **config: object) -> None:
        self.kind = kind
        self.config = config
        json.dumps(config)  # fail at import time, not save time

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"kind": self.kind}
        if self.config:
            d["config"] = dict(self.config)
        return d

    def __repr__(self) -> str:
        return f"Widget({self.kind!r}, {self.config!r})"

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


def _input_spec(param: inspect.Parameter, widget: Optional[Widget] = None) -> dict:
    type_name = _type_name(param.annotation)
    required = param.default is inspect.Parameter.empty
    default, default_repr = (None, None)
    if not required:
        default, default_repr = _jsonify_default(param.default)

    # A declared widget overrides the type-derived one (A-D2); undeclared inputs
    # keep today's derivation unchanged.
    widget_dict = widget.to_dict() if widget is not None else _widget_for(type_name)

    entry: dict[str, Any] = {
        "name": param.name,
        "type": type_name or "Any",
        "kind": _KIND_LABEL[param.kind],
        "required": required,
        "default": default,
        "widget": widget_dict,
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
    widgets: Optional[dict[str, Widget]] = None,
    dynamic: Optional[DerivedInputs] = None,
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
        widgets: per-parameter editing-widget declarations (ADR 0005 A-D2), keyed
            by parameter name. A declared :class:`Widget` overrides the
            type-derived one; a key naming no parameter raises ``EngineError`` at
            import time.
        dynamic: a :class:`DerivedInputs` declaration (ADR 0007). A node with it
            derives extra input sockets from one literal parameter's value; the
            spec gains an additive ``dynamicInputs`` marker naming that parameter.
            A dynamic node **must** have a ``**kwargs`` receptacle (the derived
            values arrive as keyword arguments); the receptacle itself is not a
            socket.
        module / qualname: override the identity (defaults to ``fn.__module__`` /
            ``fn.__qualname__``); together they form the collision-proof id.

    Raises:
        EngineError: the callable uses ``*args`` (not addressable as named
            sockets), uses ``**kwargs`` without a ``dynamic=`` declaration, is
            declared ``dynamic=`` without a ``**kwargs`` receptacle or names a
            deriving parameter that does not exist, or a ``widgets`` key names no
            parameter.
    """
    signature = inspect.signature(fn)
    short_name = name or fn.__name__
    module = module or fn.__module__
    qualname = qualname or fn.__qualname__

    widgets = widgets or {}
    unknown = set(widgets) - set(signature.parameters)
    if unknown:
        names = ", ".join(sorted(repr(n) for n in unknown))
        raise EngineError(
            f"{short_name!r} declares widget(s) for unknown parameter(s): {names}"
        )

    inputs = []
    has_var_keyword = False
    for param in signature.parameters.values():
        if param.kind == param.VAR_POSITIONAL:
            raise EngineError(
                f"{short_name!r} uses *args, which cannot be a named input "
                f"socket; wrap it in a fixed-signature function"
            )
        if param.kind == param.VAR_KEYWORD:
            has_var_keyword = True
            if dynamic is None:
                raise EngineError(
                    f"{short_name!r} uses **kwargs, which cannot be named input "
                    f"sockets; only a node with a dynamic= declaration (ADR 0007) "
                    f"may have a **kwargs receptacle for its derived values"
                )
            continue  # the receptacle is not a socket — the derived entries are
        inputs.append(_input_spec(param, widgets.get(param.name)))

    if dynamic is not None:
        if not has_var_keyword:
            raise EngineError(
                f"{short_name!r} declares dynamic= but has no **kwargs receptacle "
                f"for the derived values (ADR 0007 D1)"
            )
        if dynamic.param not in signature.parameters:
            raise EngineError(
                f"{short_name!r} declares dynamic= on parameter {dynamic.param!r}, "
                f"which is not a declared parameter"
            )

    spec: dict[str, Any] = {
        "id": f"{module}.{qualname}",
        "name": short_name,
        "title": title or short_name,
        "module": module,
        "qualname": qualname,
        "doc": inspect.getdoc(fn) or "",
        "inputs": inputs,
        "outputs": _output_specs(outputs, signature.return_annotation),
    }
    if dynamic is not None:
        spec["dynamicInputs"] = {"param": dynamic.param}
    return spec


def is_multi_output(spec: dict) -> bool:
    """True when a node has >1 output socket (its callable returns a keyed dict)."""
    return len(spec["outputs"]) > 1
