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

Pure standard library.
"""

from __future__ import annotations

import csv
import json

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


def _entry_value(entry: object) -> object:
    """The number an entry carries — bare, or inside a ``value`` field.

    Two accepted spellings, because a source often wants to say more about a
    value than the value itself: ``{"b": 220}`` and
    ``{"b": {"value": 220, "unit": "mm"}}`` both mean 220. Anything else the
    caller sees as-is and rejects with its own message.
    """
    if isinstance(entry, dict) and "value" in entry:
        return entry["value"]
    return entry


@node
def pick(data: dict, key: str = "") -> float | None:
    """One named value out of a JSON object.

    ``data`` is an object keyed by name (from :func:`read_json` or any node that
    emits a ``dict``); ``key`` names the value to take. The entry may be the
    number itself or a record carrying it under ``value`` — that second form is
    what lets a source keep provenance (a unit, a code reference) next to the
    number instead of in a second file.

    JSON ``null`` yields ``None``: the value is *absent by intent*, which is a
    different statement from a missing key. Downstream, ``sheet``'s calc nodes
    read that as an **empty given** — the ``–`` an engineering sheet prints for
    a quantity that does not apply. A missing key, by contrast, is a wiring
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

    value = _entry_value(data[key])
    if value is None:
        return None
    # bool is an int subclass, and a flag is not a quantity.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UserError(
            f"key {key!r} must hold a number or null, got {value!r} "
            f"({type(value).__name__})"
        )
    return float(value)


NODES = [read_csv, mock_api, read_json, pick]

__all__ = ["read_csv", "mock_api", "read_json", "pick", "NODES"]
