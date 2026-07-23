"""``ENTRY_POINTS`` — ``@main`` registers viewable entry points (ADR 0009 D1–D3)."""

from __future__ import annotations

import pytest

from engine import ENTRY_POINTS, EntryPointRegistry, graph, main, node


@pytest.fixture(autouse=True)
def _clean_this_module():
    """Drop anything this test module registered, before and after each test."""
    ENTRY_POINTS.unregister_module(__name__)
    yield
    ENTRY_POINTS.unregister_module(__name__)


@node
def _leaf(x: int = 0) -> int:
    return x + 1


def test_main_registers_module_qualname_file_doc_title():
    @main
    def readings_report(x: int = 0) -> int:
        """Reads things and reports.

        Longer body that must not leak into the one-line doc.
        """
        return _leaf(x)

    assert __name__ in ENTRY_POINTS
    entry = ENTRY_POINTS.get(__name__)
    assert entry["module"] == __name__
    assert entry["qualname"].endswith("readings_report")
    assert entry["file"] and entry["file"].endswith("test_authoring_entry_points.py")
    assert entry["doc"] == "Reads things and reports."
    # Derived title: un-snake-cased function name (ADR 0009 D1).
    assert entry["title"].endswith("report") and entry["title"][0].isupper()


def test_graph_composites_stay_unlisted():
    @graph
    def sub_wiring(x: int = 0) -> int:
        return _leaf(x)

    assert __name__ not in ENTRY_POINTS


def test_reimport_reregisters_dedup_key_is_module():
    @main
    def first(x: int = 0) -> int:
        return _leaf(x)

    @main
    def second(x: int = 0) -> int:
        return _leaf(x)

    entries = [e for e in ENTRY_POINTS.entries() if e["module"] == __name__]
    assert len(entries) == 1  # one entry per module — the re-registration won
    assert entries[0]["qualname"].endswith("second")


def test_title_override():
    @main(title="Nice Name")
    def ugly_internal_name(x: int = 0) -> int:
        return _leaf(x)

    assert ENTRY_POINTS.get(__name__)["title"] == "Nice Name"


def test_registry_entries_are_copies():
    @main
    def report(x: int = 0) -> int:
        return _leaf(x)

    ENTRY_POINTS.get(__name__)["title"] = "mutated"
    assert ENTRY_POINTS.get(__name__)["title"] != "mutated"


def test_standalone_registry_is_isolated():
    reg = EntryPointRegistry()
    assert reg.entries() == []
    assert "anything" not in reg
    assert reg.unregister_module("anything") is False
