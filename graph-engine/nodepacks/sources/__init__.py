"""``sources`` — interchangeable data-source nodes.

Two nodes that produce the **same shape** (a ``list`` of ``float`` readings) so
they can be swapped one-for-one in a graph:

* :func:`read_csv` — read a named column out of a CSV file on disk.
* :func:`mock_api` — an in-process, network-free mock "API client" that returns
  the same list shape without any HTTP.

Because both emit an identical ``result`` socket (``list``), swapping
``read_csv`` for ``mock_api`` changes exactly one node's type and leaves the rest
of the graph — and its output — unchanged. That is the CSV↔API source swap.

Pure standard library.
"""

from __future__ import annotations

import csv

from engine import node

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


NODES = [read_csv, mock_api]

__all__ = ["read_csv", "mock_api", "NODES"]
