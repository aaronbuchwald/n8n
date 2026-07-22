"""``calc`` — a simple-math node pack.

Plain ``@node`` functions for the common reductions (sum, mean, median, min,
max) plus a ``render_summary`` node that turns computed values into a small,
self-contained HTML card. Pure standard library: the statistics come from the
stdlib :mod:`statistics` module, and the card carries its styling inline (no
external or CDN assets).

Every function here is an ordinary Python callable first and a node second — the
``@node`` decorator only registers it with the engine by its ``module.qualname``
id (``calc.total``, ``calc.average``, …). Import and call them directly and they
behave like normal functions.
"""

from __future__ import annotations

import statistics

from engine import node


@node
def total(values: list) -> float:
    """Sum the values."""
    return float(sum(values))


@node
def average(values: list) -> float:
    """Arithmetic mean of the values."""
    return float(statistics.fmean(values))


@node
def median(values: list) -> float:
    """Median (middle value) of the values."""
    return float(statistics.median(values))


@node
def minimum(values: list) -> float:
    """Smallest of the values."""
    return float(min(values))


@node
def maximum(values: list) -> float:
    """Largest of the values."""
    return float(max(values))


@node
def render_summary(
    title: str = "Summary",
    average: float = 0.0,
    median: float = 0.0,
) -> str:
    """Render a small, self-contained HTML card (inline CSS, no CDN assets).

    Shows the ``average`` and ``median`` under ``title``. Returns a single
    ``<div>`` string safe to embed anywhere.
    """
    return (
        '<div style="font-family:system-ui,-apple-system,sans-serif;'
        "max-width:20rem;padding:1rem;border:1px solid #ddd;border-radius:8px;"
        'box-shadow:0 1px 3px rgba(0,0,0,.08)">'
        f'<h1 style="font-size:1rem;margin:0 0 .5rem">{title}</h1>'
        '<dl style="margin:0;display:grid;grid-template-columns:auto auto;'
        'gap:.25rem 1rem;font-size:.9rem">'
        '<dt style="color:#666">Average</dt>'
        f'<dd style="margin:0;font-weight:600">{average:g}</dd>'
        '<dt style="color:#666">Median</dt>'
        f'<dd style="margin:0;font-weight:600">{median:g}</dd>'
        "</dl></div>"
    )


# All node types this pack defines (handy for registries / snapshots).
NODES = [total, average, median, minimum, maximum, render_summary]

__all__ = [
    "total",
    "average",
    "median",
    "minimum",
    "maximum",
    "render_summary",
    "NODES",
]
