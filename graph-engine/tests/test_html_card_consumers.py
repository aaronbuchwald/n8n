"""The `html-card` kind's v1 consumers (ADR 0010 D6, stream 10-K).

10-E proved the engine seam (`tests/test_renderer_spec.py`); this proves the
three pack-side declarations that light it up:

* ``sym.render_math_card``, ``table.table_summary`` and the showcase
  ``dashboard`` each declare ``renderer=Renderer("html-card", socket=...,
  height=...)`` and serialise it to the frozen ``{kind, config}`` wire shape;
* each declared ``socket`` names a real output socket (the import-time
  validation these modules now exercise for real);
* the decorated nodes still run — the declaration is spec-side view data and
  must not change the callables' behaviour.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import sym
import table

SHOWCASE_DIR = Path(__file__).resolve().parents[1] / "examples" / "showcase"


def _showcase():
    if str(SHOWCASE_DIR) not in sys.path:
        sys.path.insert(0, str(SHOWCASE_DIR))
    return importlib.import_module("showcase")


def _assert_declares_html_card(spec: dict, height: int) -> None:
    assert spec["renderer"] == {
        "kind": "html-card",
        "config": {"socket": "result", "height": height},
    }
    # The declared socket names a real output (validated at import, asserted
    # here so a future outputs= rename cannot silently orphan the renderer).
    assert spec["renderer"]["config"]["socket"] in {o["name"] for o in spec["outputs"]}


def test_render_math_card_declares_html_card():
    _assert_declares_html_card(sym.render_math_card.spec, height=220)


def test_table_summary_declares_html_card():
    _assert_declares_html_card(table.table_summary.spec, height=200)


def test_showcase_dashboard_declares_html_card():
    _assert_declares_html_card(_showcase().dashboard.spec, height=420)


def test_decorated_nodes_still_run():
    card = sym.render_math_card("Roots", "<math><mi>x</mi></math>", "x = 2")
    assert "<math><mi>x</mi></math>" in card and "Roots" in card

    summary = table.table_summary({"columns": ["a"], "rows": [[1]]}, title="T")
    assert "<table" in summary and "T" in summary

    report = _showcase().dashboard(table_html=summary, math_html=card, title="Both")
    assert summary in report and card in report
