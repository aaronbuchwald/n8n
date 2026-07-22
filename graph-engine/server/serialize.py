"""JSON-safe serialisation of run outputs.

Node outputs can be any Python object. JSON-native values pass through; anything
else degrades to a tagged ``{"$repr": ..., "$type": ...}`` placeholder (with a
size cap) so a response is always serialisable and the UI can still show
*something*. This is the cheap version of ADR 0001's "JSON values + opaque
handles" — large/opaque values become previews, not failures.
"""

from __future__ import annotations

from typing import Any

_JSON_SCALARS = (str, int, float, bool, type(None))
_REPR_CAP = 2000


def to_jsonable(value: Any) -> Any:
    """Return a JSON-serialisable view of ``value``."""
    if isinstance(value, _JSON_SCALARS):
        return value
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    text = repr(value)
    if len(text) > _REPR_CAP:
        text = text[:_REPR_CAP] + f"… (+{len(text) - _REPR_CAP} chars)"
    return {"$repr": text, "$type": type(value).__name__}
