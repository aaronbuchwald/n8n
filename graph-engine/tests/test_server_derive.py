"""Tests for ``POST /api/specs/{spec_id}/derive`` (ADR 0007 D4).

Python-authoritative socket derivation over HTTP: the UI posts a draft equation
and gets back the exact socket list the engine would derive at bind time.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import sym  # noqa: F401 - registers sym.* into DEFAULT_REGISTRY
from engine import DEFAULT_REGISTRY
from server import create_app


def _client() -> TestClient:
    return TestClient(create_app(DEFAULT_REGISTRY))


def test_derive_returns_the_derived_sockets():
    r = _client().post("/api/specs/sym.handcalc/derive", json={"value": "margin = C_min - F_max"})
    assert r.status_code == 200
    inputs = r.json()["inputs"]
    assert [i["name"] for i in inputs] == ["C_min", "F_max"]
    assert all(i["derived"] and i["kind"] == "keywordOnly" for i in inputs)


def test_derive_reports_a_user_error_as_422():
    r = _client().post("/api/specs/sym.handcalc/derive", json={"value": "x = = 3"})
    assert r.status_code == 422
    err = r.json()["errors"][0]
    assert err["code"] == "UserError"
    assert "line 1" in err["message"]


def test_derive_404_for_unknown_spec():
    r = _client().post("/api/specs/sym.nope/derive", json={"value": "x = 1"})
    assert r.status_code == 404


def test_derive_404_for_non_dynamic_spec():
    r = _client().post("/api/specs/sym.typeset_calc/derive", json={"value": "x = 1"})
    assert r.status_code == 404


def test_editing_the_equation_adds_a_new_required_socket():
    client = _client()
    before = client.post("/api/specs/sym.handcalc/derive", json={"value": "margin = C_min - F_max"}).json()
    after = client.post("/api/specs/sym.handcalc/derive", json={"value": "margin = C_min - F_max - safety"}).json()
    assert [i["name"] for i in before["inputs"]] == ["C_min", "F_max"]
    # The added symbol appears as a new, required socket (no silent default).
    assert [i["name"] for i in after["inputs"]] == ["C_min", "F_max", "safety"]
    new_socket = after["inputs"][-1]
    assert new_socket["required"] is True and new_socket["default"] is None
