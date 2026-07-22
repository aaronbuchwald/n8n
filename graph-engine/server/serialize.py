"""JSON-safe serialisation of run outputs.

Node outputs can be any Python object. JSON-native values pass through; anything
else — including cycles and non-finite floats — degrades to a tagged
``{"$repr": ..., "$type": ...}`` placeholder (with a size cap) so a response is
ALWAYS serialisable and the UI can still show *something*. This is the cheap
version of ADR 0001's "JSON values + opaque handles" — large/opaque values
become previews, not failures or silent corruption.
"""

from __future__ import annotations

import math
from typing import Any, Optional

_REPR_CAP = 2000


def _preview(value: Any, repr_text: Optional[str] = None) -> dict:
    text = repr_text if repr_text is not None else repr(value)
    if len(text) > _REPR_CAP:
        text = text[:_REPR_CAP] + f"… (+{len(text) - _REPR_CAP} chars)"
    return {"$repr": text, "$type": type(value).__name__}


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
    return _preview(value)
