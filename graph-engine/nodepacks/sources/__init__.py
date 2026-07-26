"""``sources`` — generic data-source nodes.

Nothing here knows what the numbers *mean*; every node reads a file (or a
fixture) and hands back a plain Python value. Two families:

**Column readings** — the same shape (a ``list`` of ``float``) from two places,
so they can be swapped one-for-one in a graph:

* :func:`read_csv` — read a named column out of a CSV file on disk.
* :func:`mock_api` — an in-process, network-free mock "API client" that returns
  the same list shape without any HTTP.

Because both emit an identical ``result`` socket (``list``), swapping
``read_csv`` for ``mock_api`` changes exactly one node's type and leaves the rest
of the graph — and its output — unchanged. That is the CSV↔API source swap.

**Named scalars** — a JSON document, then one value at a time:

* :func:`read_json` — read a JSON object off disk.
* :func:`pick` — take one named value out of such an object.

The pair is deliberately split. One ``pick`` per value means each value is its
own node with its own wire, so any single one can later be re-pointed at a
different source (another file, an API node, a computed value) without touching
the others — which a one-node "read these nine keys" reader could not do.

**One node writes** — :func:`write_json`, and it is the first node in this
engine that touches disk in the write direction. That is a capability change,
not a convenience, so its reach is stated here rather than left implicit:

* the destination is **relative, always** — resolved against the working
  directory the graph runs in, which is the running program's own directory.
  An absolute path is refused outright;
* it may not climb out of that directory: a ``..`` component is refused, and so
  is any path whose real location (after following symlinks) lands outside;
* it writes exactly one file and creates no directories.

**Relationship to ADR 0003's ``mounts``.** The right way to express "this graph
may write here" is the environment descriptor: ``mounts: [{"path": …, "mode":
"rw"}]``, resolved and confined by the mount guard the C-stream will own. That
guard does not exist yet, and this node is **not** it — it is a narrow,
hard-coded stand-in that grants exactly one thing (write inside the run
directory) to exactly one node, so a graph can produce an artifact before the
descriptor can grant the capability properly. The design is unfinished on
purpose: when ``mounts`` is enforced, this node's rule should become the
guard's, and the hard-coding here should go. Until then, treat it the way
ADR 0003 asks its own descriptor to be treated — accident-proof, not
malice-proof.

Pure standard library.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from engine import UserError, node

# In-process fixtures for the mock API — no network, ever. Keyed by dataset name
# so a graph can pick a series the way it would pick an API endpoint.
#
# NOTE: the CSV↔mock-API "source swap" yields identical output only because
# "readings" below mirrors the values shipped in examples/readings/readings.csv.
# This parity is a fixture convenience, not an enforced invariant — editing the
# CSV without updating this list breaks it (guarded by the swap test against the
# shipped fixture). A real API would of course return its own data.
_MOCK_DATASETS: dict[str, list[float]] = {
    "readings": [10.0, 20.0, 30.0, 40.0],
    "empty": [],
}


@node
def read_csv(path: str = "readings.csv", column: str = "value") -> list:
    """Read one named ``column`` of a CSV into a list of floats.

    The CSV must have a header row; ``column`` selects which column to read
    (default ``value``). Rows whose cell is blank are skipped. Extra columns are
    ignored, so a one-or-few-column file both work.
    """
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or column not in reader.fieldnames:
            raise ValueError(f"CSV {path!r} has no column {column!r}")
        return [float(row[column]) for row in reader if row.get(column) not in (None, "")]


@node
def mock_api(dataset: str = "readings", offline: bool = True) -> list:
    """In-process mock "API client" returning the same shape as :func:`read_csv`.

    Returns a list of float readings for ``dataset`` from a built-in fixture — no
    HTTP request is made. ``offline`` defaults to ``True`` and any attempt to run
    it with ``offline=False`` is refused, keeping the node network-free by
    default (and by design in this pack).
    """
    if not offline:
        raise ValueError("mock_api is network-free; only offline=True is supported")
    if dataset not in _MOCK_DATASETS:
        raise ValueError(f"unknown dataset {dataset!r}; try one of {sorted(_MOCK_DATASETS)}")
    return list(_MOCK_DATASETS[dataset])


@node
def read_json(path: str = "inputs.json") -> dict:
    """Read a JSON **object** from ``path``.

    The whole document, as a ``dict`` — no key selection, no coercion, no
    knowledge of what is inside. Use :func:`pick` to take a value out of it. A
    document whose top level is an array or a scalar is refused: the thing
    downstream nodes address by name has to be an object.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        raise UserError(f"no such JSON file: {path!r}") from None
    except json.JSONDecodeError as error:
        raise UserError(f"{path!r} is not valid JSON ({error})") from None
    if not isinstance(data, dict):
        raise UserError(
            f"{path!r} must hold a JSON object at the top level, got "
            f"{type(data).__name__}"
        )
    return data


@node
def pick(data: dict, key: str = "") -> float | dict | None:
    """One named entry out of a JSON object — whatever is there.

    ``data`` is an object keyed by name (from :func:`read_json` or any node that
    emits a ``dict``); ``key`` names the entry to take. Three shapes come back,
    and the node does not choose between them — the source did:

    * a **number** — returned as a ``float``;
    * ``null`` — returned as ``None``. The value is *absent by intent*, which is
      a different statement from a missing key. A consumer is free to read that
      as "not applicable"; ``sheet``'s calc nodes render it as an empty given.
    * an **object** — returned verbatim. A source that wants to say more about a
      value than the value itself (a unit, a code reference, a timestamp) puts
      it beside the number, and this node hands the whole record on rather than
      throwing the context away.

    Interpreting a record is the *consumer's* business, deliberately: this node
    knows only that it picked something. A missing key, by contrast, is a wiring
    mistake and raises, listing what the object does have.
    """
    if not isinstance(data, dict):
        raise UserError(
            f"the 'data' input must be a JSON object (wire it from read_json), "
            f"got {type(data).__name__}"
        )
    if key not in data:
        known = ", ".join(repr(k) for k in data) or "(nothing)"
        raise UserError(f"no key {key!r} in the data; it has: {known}")

    entry = data[key]
    if entry is None or isinstance(entry, dict):
        return entry
    # bool is an int subclass, and a flag is not a quantity.
    if isinstance(entry, bool) or not isinstance(entry, (int, float)):
        raise UserError(
            f"key {key!r} must hold a number, null, or an object, got {entry!r} "
            f"({type(entry).__name__})"
        )
    return float(entry)


@node
def write_json(data: dict, path: str = "artifact.json") -> str:
    """Write ``data`` to ``path`` as JSON; returns the file it wrote.

    The one writing node in the pack. ``data`` is any JSON-serialisable value —
    typically a record a selector node produced — written pretty-printed (two
    spaces, keys in their existing order, non-ASCII kept as itself) with a
    trailing newline, so the artifact reads as a document rather than one long
    line.

    **Where it may write, and why that is the whole design.** ``path`` is
    resolved against the working directory the graph runs in — the running
    program's own directory — and must stay inside it:

    * an **absolute** path is refused; the destination is the run's business,
      not the graph author's;
    * a ``..`` component is refused;
    * a path whose real location escapes the run directory through a
      **symlink** is refused, checked after resolution rather than by reading
      the string.

    Each refusal raises :class:`engine.UserError` naming the offending path and
    stating the rule — a graph that asks for more than the node may give gets a
    sentence about the boundary, not a traceback.

    The rule is hard-coded because the descriptor that should grant this
    properly — ADR 0003's ``mounts``, with the mount guard resolving and
    confining paths — is not enforced yet. See the module docstring: this node
    is a deliberate stand-in, and its containment is accident-proofing, not a
    security boundary.

    The returned string is the resolved file, so a downstream node (or a person
    reading the run output) is told exactly what was written, not what was
    asked for.
    """
    if not isinstance(path, str) or not path.strip():
        raise UserError("write_json needs a 'path' to write to; it was empty")

    root = Path.cwd().resolve()
    rule = (
        f"write_json may only write inside the directory the graph runs in "
        f"({root}); the path must be relative and stay under it"
    )
    candidate = Path(path)
    if candidate.is_absolute():
        raise UserError(f"refusing to write to the absolute path {path!r}: {rule}")
    if ".." in candidate.parts:
        raise UserError(f"refusing to write to {path!r}: it climbs out with '..'; {rule}")

    target = (root / candidate).resolve()
    if target == root:
        raise UserError(f"refusing to write to {path!r}: it names the run directory itself")
    if not target.is_relative_to(root):
        # Reached here only via a symlink: the string itself is clean.
        raise UserError(
            f"refusing to write to {path!r}: it resolves to {target}, outside "
            f"the run directory (a symlink leads out of it); {rule}"
        )
    if not target.parent.is_dir():
        raise UserError(
            f"cannot write {path!r}: its directory {target.parent} does not "
            f"exist, and write_json creates no directories"
        )

    text = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False)
    target.write_text(text + "\n", encoding="utf-8")
    return str(target)


NODES = [read_csv, mock_api, read_json, pick, write_json]

__all__ = ["read_csv", "mock_api", "read_json", "pick", "write_json", "NODES"]
