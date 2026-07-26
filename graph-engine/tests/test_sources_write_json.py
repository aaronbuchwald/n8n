"""Tests for ``sources.write_json`` — the one node that writes to disk.

The behaviour worth testing is not "it writes a file" but **where it refuses
to**: the destination is relative, resolved against the directory the graph
runs in, and it may not leave that directory — not by being absolute, not via
``..``, and not through a symlink.

Every test runs in a ``tmp_path`` working directory, which is what the node
treats as the run directory (see the module docstring in ``nodepacks/sources``:
this is a hard-coded stand-in until ADR 0003's ``mounts`` is enforced).

Run with:  uv run --extra dev --extra sym python -m pytest -q
"""

from __future__ import annotations

import json

import pytest

from engine import UserError
from sources import write_json

RECORD = {"value": 297.175507, "unit": "kN", "ref": "RFEM 10103/1578 @ 6.15 m · LK67"}


@pytest.fixture(autouse=True)
def _run_directory(tmp_path, monkeypatch):
    """Every test's run directory — what the node confines writes to."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


# -- what it writes -----------------------------------------------------------


def test_it_writes_the_record_as_json_and_returns_the_file(tmp_path):
    written = write_json(RECORD, "governing.json")

    assert written == str(tmp_path / "governing.json")
    assert json.loads((tmp_path / "governing.json").read_text(encoding="utf-8")) == RECORD


def test_it_writes_a_document_not_one_long_line(tmp_path):
    write_json(RECORD, "governing.json")
    text = (tmp_path / "governing.json").read_text(encoding="utf-8")

    assert text.startswith("{\n  ") and text.endswith("}\n")
    assert '"ref": "RFEM 10103/1578 @ 6.15 m · LK67"' in text  # not ·-escaped


def test_key_order_is_the_records_own(tmp_path):
    write_json({"value": 1, "unit": "kN", "ref": "x", "component": "Vz"}, "out.json")
    text = (tmp_path / "out.json").read_text(encoding="utf-8")

    assert list(json.loads(text)) == ["value", "unit", "ref", "component"]
    assert text.index('"value"') < text.index('"component"')


def test_it_writes_into_an_existing_subdirectory(tmp_path):
    (tmp_path / "out").mkdir()

    assert write_json(RECORD, "out/governing.json") == str(tmp_path / "out" / "governing.json")


def test_a_rerun_overwrites_rather_than_appends(tmp_path):
    write_json({"value": 1}, "out.json")
    write_json({"value": 2}, "out.json")

    assert json.loads((tmp_path / "out.json").read_text(encoding="utf-8")) == {"value": 2}


# -- where it refuses to write ------------------------------------------------


def test_an_absolute_path_is_refused(tmp_path):
    target = tmp_path / "inside.json"  # inside the run dir, but absolute anyway

    with pytest.raises(UserError) as caught:
        write_json(RECORD, str(target))

    message = str(caught.value)
    assert str(target) in message  # names the offending path
    assert "absolute" in message
    assert "may only write inside the directory the graph runs in" in message
    assert not target.exists()


def test_climbing_out_with_dotdot_is_refused(tmp_path):
    with pytest.raises(UserError) as caught:
        write_json(RECORD, "../escaped.json")

    message = str(caught.value)
    assert "'../escaped.json'" in message and "climbs out with '..'" in message
    assert not (tmp_path.parent / "escaped.json").exists()


def test_a_dotdot_buried_mid_path_is_refused_too(tmp_path):
    (tmp_path / "out").mkdir()

    with pytest.raises(UserError):
        write_json(RECORD, "out/../../escaped.json")
    assert not (tmp_path.parent / "escaped.json").exists()


def test_a_symlink_leading_out_of_the_run_directory_is_refused(tmp_path):
    outside = tmp_path.parent / "outside"
    outside.mkdir(exist_ok=True)
    (tmp_path / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(UserError) as caught:
        write_json(RECORD, "link/escaped.json")

    message = str(caught.value)
    assert "'link/escaped.json'" in message  # names the offending path
    assert "symlink leads out of it" in message
    assert "may only write inside the directory the graph runs in" in message
    assert not (outside / "escaped.json").exists()


def test_a_symlinked_file_pointing_out_is_refused(tmp_path):
    outside = tmp_path.parent / "outside-file.json"
    outside.write_text("{}\n", encoding="utf-8")
    (tmp_path / "link.json").symlink_to(outside)

    with pytest.raises(UserError):
        write_json(RECORD, "link.json")
    assert outside.read_text(encoding="utf-8") == "{}\n"


def test_a_symlink_staying_inside_the_run_directory_is_fine(tmp_path):
    """The rule is about *escaping*, not about symlinks as such."""
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)

    assert write_json(RECORD, "link/governing.json") == str(
        tmp_path / "real" / "governing.json"
    )


def test_an_empty_path_is_refused():
    with pytest.raises(UserError) as caught:
        write_json(RECORD, "  ")
    assert "needs a 'path' to write to" in str(caught.value)


def test_a_missing_directory_is_refused_rather_than_created(tmp_path):
    with pytest.raises(UserError) as caught:
        write_json(RECORD, "nowhere/governing.json")

    assert "creates no directories" in str(caught.value)
    assert not (tmp_path / "nowhere").exists()


def test_the_run_directory_itself_is_not_a_destination():
    with pytest.raises(UserError):
        write_json(RECORD, ".")


# -- it is a node, like every other in the pack -------------------------------


def test_it_is_registered_as_a_node_type():
    from engine import DEFAULT_REGISTRY

    spec = DEFAULT_REGISTRY.spec("sources.write_json")
    assert [i["name"] for i in spec["inputs"]] == ["data", "path"]
    assert [o["name"] for o in spec["outputs"]] == ["result"]
