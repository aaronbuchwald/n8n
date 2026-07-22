"""``table.apply_recipe`` declares the ``table-recipe`` widget (ADR 0005 C-ui).

The grid editor (web/src/widgets/table/) resolves by ``widget.kind`` in the JS
registry; this proves the Python side of that seam: the ``recipe`` input spec
carries the frozen ``{kind: "table-recipe"}`` declaration, and the declaration
changes nothing else about the node (other inputs, behavior).
"""

from __future__ import annotations

import table  # noqa: F401  -- importing registers the pack's nodes
from engine import DEFAULT_REGISTRY


def _input(spec: dict, name: str) -> dict:
    return next(i for i in spec["inputs"] if i["name"] == name)


def test_apply_recipe_spec_declares_table_recipe_widget():
    spec = DEFAULT_REGISTRY.spec("table.apply_recipe")
    assert _input(spec, "recipe")["widget"] == {"kind": "table-recipe"}


def test_other_inputs_keep_their_derived_widgets():
    spec = DEFAULT_REGISTRY.spec("table.apply_recipe")
    # `table` is dict-typed: no declared widget and no type-derived one.
    assert _input(spec, "table")["widget"] is None


def test_declaration_does_not_change_behavior():
    result = table.apply_recipe(
        {"columns": ["a"], "rows": [[1.0], [5.0]]},
        {"version": 1, "ops": [{"op": "filter", "expr": "a > 2"}]},
    )
    assert result == {"columns": ["a"], "rows": [[5.0]]}
