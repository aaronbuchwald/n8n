"""Tests for server.serialize.to_jsonable — cycle- and NaN/Inf-safety."""

import math

from server.serialize import to_jsonable


def test_json_native_passthrough():
    assert to_jsonable({"a": [1, 2.5, "x", True, None]}) == {"a": [1, 2.5, "x", True, None]}


def test_cycle_becomes_preview():
    a: list = []
    a.append(a)
    out = to_jsonable(a)
    assert out[0] == {"$repr": "<cycle>", "$type": "list"}


def test_shared_non_cyclic_reference_is_not_flagged():
    shared = [1, 2]
    out = to_jsonable([shared, shared])  # a DAG, not a cycle
    assert out == [[1, 2], [1, 2]]


def test_non_finite_floats_are_previewed_not_nulled():
    assert to_jsonable(math.inf) == {"$repr": "inf", "$type": "float"}
    assert to_jsonable(math.nan)["$type"] == "float"


def test_opaque_object_becomes_preview():
    class Widget:
        pass

    out = to_jsonable(Widget())
    assert out["$type"] == "Widget" and "$repr" in out
