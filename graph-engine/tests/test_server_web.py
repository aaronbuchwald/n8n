"""Tests for the dev-ergonomics additions: SPA static mount + view-URL helper.

None of these touch the interactive Enter/webbrowser path — they only assert the
static mount serves the built app at ``/`` (using a temp dir, no real build) and
that ``/api/*`` still works with the mount present, plus a unit test of the
view-URL helper.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine import NodeRegistry
from server import create_app
from server.__main__ import _wait_for_enter_then_open, view_url


def total(values: list) -> float:
    return sum(values)


@pytest.fixture()
def registry() -> NodeRegistry:
    reg = NodeRegistry()
    reg.register(total, module="calc", qualname="total")
    return reg


@pytest.fixture()
def web_dist(tmp_path: Path) -> Path:
    """A stand-in for a built ``web/dist`` — just an index.html, no real build."""
    (tmp_path / "index.html").write_text("<!doctype html><title>graph-engine</title><div id=app></div>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('hi')")
    return tmp_path


def test_view_url_is_same_origin_root():
    assert view_url("127.0.0.1", 8000) == "http://127.0.0.1:8000/"
    assert view_url("0.0.0.0", 4173) == "http://0.0.0.0:4173/"


def test_static_mount_serves_index_at_root(registry, web_dist):
    client = TestClient(create_app(registry, web_dist=web_dist))
    r = client.get("/")
    assert r.status_code == 200
    assert "graph-engine" in r.text
    # a hashed asset is reachable too
    assert client.get("/assets/app.js").status_code == 200


def test_api_still_works_with_static_mount_present(registry, web_dist):
    client = TestClient(create_app(registry, web_dist=web_dist))
    body = client.get("/api/specs").json()
    assert body["version"] == "0.2.0"
    assert set(body["specs"]) == {"calc.total"}


def test_build_hint_served_when_dist_missing(registry, tmp_path):
    # Point at a non-existent dir → no static mount; "/" serves a friendly build
    # hint (not a raw 404) and the API still works.
    client = TestClient(create_app(registry, web_dist=tmp_path / "does-not-exist"))
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "pnpm build" in r.text  # tells the user how to build the web
    assert "/api/specs" in r.text  # links to the live API
    assert client.get("/api/specs").status_code == 200


def test_enter_handler_is_callable_and_exits_on_eof():
    # No TTY here: feeding an exhausted iterator (EOF) must return quietly, not raise.
    import io

    original = None
    try:
        import sys

        original = sys.stdin
        sys.stdin = io.StringIO("")  # immediate EOF
        _wait_for_enter_then_open("http://127.0.0.1:8000/")  # must not raise
    finally:
        if original is not None:
            sys.stdin = original
