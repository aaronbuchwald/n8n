"""JSON-safe serialisation of run outputs.

Node outputs can be any Python object. JSON-native values pass through; anything
else — including cycles and non-finite floats — degrades to a tagged
``{"$repr": ..., "$type": ...}`` placeholder (with a size cap) so a response is
ALWAYS serialisable and the UI can still show *something*. This is the cheap
version of ADR 0001's "JSON values + opaque handles" — large/opaque values
become previews, not failures or silent corruption.

Between those two, a value may **describe itself**: an object offering
``to_jsonable()`` or ``to_dict()`` gets that view serialised instead of a repr
(ADR 0021 D2). This is a *protocol*, not a dependency — a structural probe, so
the engine imports no pack and knows nothing about any pack's types; anything
that can say what it is in JSON opts in by having the method.
"""

from __future__ import annotations

import math
from typing import Any, Optional

_REPR_CAP = 2000

# Probed in order; the first one a value offers wins. `to_jsonable` is the
# purpose-named hook, `to_dict` the de-facto spelling types already ship (e.g.
# calcsheet's versioned Result form).
_JSON_HOOKS = ("to_jsonable", "to_dict")

# Sentinel: "this value offered no usable JSON view of itself".
_NO_VIEW = object()


def _preview(value: Any, repr_text: Optional[str] = None) -> dict:
    text = repr_text if repr_text is not None else repr(value)
    if len(text) > _REPR_CAP:
        text = text[:_REPR_CAP] + f"… (+{len(text) - _REPR_CAP} chars)"
    return {"$repr": text, "$type": type(value).__name__}


def _self_view(value: Any) -> Any:
    """The value's own JSON view via the D2 protocol, or :data:`_NO_VIEW`.

    A hook that raises (or wants arguments) is treated as absent: a preview is
    always better than a failed response, which is this module's whole point.
    """
    for name in _JSON_HOOKS:
        hook = getattr(value, name, None)
        if callable(hook):
            try:
                return hook()
            except Exception:  # noqa: BLE001 — degrade to the repr preview
                return _NO_VIEW
    return _NO_VIEW


def to_jsonable(value: Any, _seen: Optional[frozenset] = None) -> Any:
    """Return a JSON-serialisable view of ``value`` (cycle- and NaN/Inf-safe)."""
    if value is None or isinstance(value, bool) or isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        # NaN/Inf are JSON-invalid and get silently nulled by many encoders —
        # surface them as a visible preview instead.
        return value if math.isfinite(value) else _preview(value)
    if isinstance(value, (dict, list, tuple)):
        seen = _seen or frozenset()
        if id(value) in seen:
            return _preview(value, "<cycle>")
        seen = seen | {id(value)}
        if isinstance(value, dict):
            return {str(k): to_jsonable(v, seen) for k, v in value.items()}
        return [to_jsonable(v, seen) for v in value]

    seen = _seen or frozenset()
    if id(value) not in seen:
        view = _self_view(value)
        if view is not _NO_VIEW:
            # Recurse: what the hook returns is a claim, not a guarantee, so it
            # runs the same gauntlet (cycles included — hence `id(value)`).
            return to_jsonable(view, seen | {id(value)})
    return _preview(value)
