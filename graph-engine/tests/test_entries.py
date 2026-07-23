"""``EntryCatalog`` — root scanning, eager import, error capture, workspace pool (ADR 0009 D2/D4)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from engine import DEFAULT_REGISTRY, ENTRY_POINTS
from server.entries import EntryCatalog, EntryLoadError, UnknownEntryError

GOOD = "epcat_good"
BROKEN = "epcat_broken"
NO_MAIN = "epcat_nomain"

GOOD_SOURCE = '''\
from engine import main, node


@node
def double(x: int = 1) -> int:
    return x * 2


@main
def good_report(x: int = 2) -> int:
    """Doubles a number."""
    doubled = double(x)
    return doubled
'''

BROKEN_SOURCE = 'raise ImportError("boom at import")\n'

NO_MAIN_SOURCE = '''\
from engine import node


@node
def triple(x: int = 1) -> int:
    return x * 3
'''


def _write_example(root: Path, name: str, source: str) -> None:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / f"{name}.py").write_text(source, encoding="utf-8")


@pytest.fixture()
def scan_root(tmp_path: Path):
    root = tmp_path / "entries"
    _write_example(root, GOOD, GOOD_SOURCE)
    _write_example(root, BROKEN, BROKEN_SOURCE)
    _write_example(root, NO_MAIN, NO_MAIN_SOURCE)
    yield root
    # Undo the global side effects of importing the temp modules.
    for name in (GOOD, BROKEN, NO_MAIN):
        sys.modules.pop(name, None)
        ENTRY_POINTS.unregister_module(name)
        DEFAULT_REGISTRY.unregister_module(name)
        entry_dir = str(root / name)
        if entry_dir in sys.path:
            sys.path.remove(entry_dir)


@pytest.fixture()
def catalog(scan_root: Path) -> EntryCatalog:
    return EntryCatalog(roots=[scan_root], default=GOOD).discover()


def _entry(catalog: EntryCatalog, entry_id: str) -> dict:
    matches = [e for e in catalog.entries() if e["id"] == entry_id]
    assert len(matches) == 1, f"expected exactly one listing for {entry_id!r}"
    return matches[0]


def test_scan_imports_and_lists_ok_entry(catalog: EntryCatalog):
    entry = _entry(catalog, GOOD)
    assert entry["status"] == "ok"
    assert entry["module"] == GOOD
    assert entry["qualname"] == "good_report"
    assert entry["title"] == "Good report"
    assert entry["path"].endswith(f"{GOOD}/{GOOD}.py")
    assert entry["dir"].endswith(GOOD)
    # The import registered the module's @node types in the shared registry.
    assert f"{GOOD}.double" in DEFAULT_REGISTRY


def test_import_error_is_listed_not_hidden(catalog: EntryCatalog):
    entry = _entry(catalog, BROKEN)
    assert entry["status"] == "error"
    assert "boom at import" in entry["error"]
    assert entry["path"].endswith(f"{BROKEN}/{BROKEN}.py")


def test_module_without_main_is_scanned_but_unlisted(catalog: EntryCatalog):
    # Imported (its @node types are in the palette) but not an entry (no @main).
    assert f"{NO_MAIN}.triple" in DEFAULT_REGISTRY
    assert all(e["id"] != NO_MAIN for e in catalog.entries())


def test_workspace_pool_is_memoized(catalog: EntryCatalog):
    first = catalog.workspace(GOOD)
    second = catalog.workspace(GOOD)
    assert first is second
    workspace, run_base_dir = first
    assert workspace.module_name == GOOD
    assert run_base_dir.name == GOOD
    assert workspace.parse_graph()["nodes"][0]["type"] == f"{GOOD}.double"


def test_unknown_id_raises_with_known_ids(catalog: EntryCatalog):
    with pytest.raises(UnknownEntryError) as excinfo:
        catalog.workspace("nope")
    assert GOOD in excinfo.value.message
    assert BROKEN in excinfo.value.message


def test_broken_entry_raises_load_error(catalog: EntryCatalog):
    with pytest.raises(EntryLoadError, match="boom at import"):
        catalog.workspace(BROKEN)


def test_bundled_examples_discover_multiple_viewable_entries():
    """The shipped demo must expose several switchable entry points (ADR 0009)."""
    catalog = EntryCatalog().discover()
    ok = {e["id"] for e in catalog.entries() if e["status"] == "ok"}
    assert {"showcase", "capacity_check", "minimal"} <= ok
