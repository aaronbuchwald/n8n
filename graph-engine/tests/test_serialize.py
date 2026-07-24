"""Tests for server.serialize.to_jsonable — cycle-, NaN/Inf-safety and the
self-description protocol (ADR 0021 D2)."""

import math

import pytest

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


# -- the self-description protocol (ADR 0021 D2) ------------------------------
#
# Structural, never nominal: nothing here imports a pack, and no pack type is
# named — a value opts in purely by having the method.


@pytest.mark.parametrize("hook", ["to_jsonable", "to_dict"])
def test_a_value_that_describes_itself_previews_as_real_json(hook):
    payload = {"schema": 1, "rows": [{"symbol": "U", "value": 57.1}]}
    Described = type("Described", (), {hook: lambda self: dict(payload)})

    assert to_jsonable(Described()) == payload


def test_the_described_view_is_itself_made_json_safe():
    """What a hook returns is a claim, not a guarantee — it is checked too."""

    class Sensor:
        def to_dict(self):
            return {"reading": math.inf, "probe": object()}

    out = to_jsonable(Sensor())
    assert out["reading"] == {"$repr": "inf", "$type": "float"}
    assert out["probe"]["$type"] == "object"


def test_a_value_without_the_protocol_still_becomes_a_preview():
    class Opaque:
        def render(self):  # a method, but not one of the hooks
            return "nope"

    out = to_jsonable(Opaque())
    assert out["$type"] == "Opaque" and "$repr" in out


def test_a_raising_hook_degrades_to_a_preview_instead_of_failing_the_response():
    class Broken:
        def to_dict(self):
            raise RuntimeError("boom")

    assert to_jsonable(Broken())["$type"] == "Broken"


def test_a_self_referential_view_terminates():
    class Loop:
        def to_dict(self):
            return {"me": self}

    assert to_jsonable(Loop())["me"]["$type"] == "Loop"
