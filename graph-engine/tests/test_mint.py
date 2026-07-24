"""Node-id minting for palette-created nodes — ADR 0011 W1 / HD4.

A palette drop mints the node id that becomes the composite's assignment
variable (ADR 0004 D3). The minted id must be a valid Python identifier and must
dodge all four collision classes, because colliding with a call name reproduces
the exact shadow ``wiring_lines`` rejects (``total = total(vals)``).

The module-aware tests build the collision set from raw authoring-module source
(``module_collision_set`` only parses source — no registry needed).
"""

from engine import mint_node_id, module_collision_set


# -- sanitisation + snake_case (HD4 identifier rules) -----------------------


def test_plain_name_is_returned_as_is():
    assert mint_node_id("total") == "total"


def test_camel_case_becomes_snake_case():
    assert mint_node_id("ReadValues") == "read_values"


def test_acronym_boundary_snake_cases():
    assert mint_node_id("readCSVFile") == "read_csv_file"


def test_non_identifier_chars_are_sanitised():
    assert mint_node_id("read table!") == "read_table"


def test_leading_digit_is_prefixed():
    assert mint_node_id("3d_render") == "n_3d_render"


def test_python_keyword_is_prefixed():
    assert mint_node_id("class") == "n_class"
    assert mint_node_id("return") == "n_return"


def test_all_punctuation_falls_back_to_node():
    assert mint_node_id("!!!") == "node"


def test_result_is_always_a_valid_identifier():
    for name in ["total", "3d", "class", "read table!", "!!!", "ReadCSV"]:
        assert mint_node_id(name).isidentifier()


# -- numeric-suffix dedupe (matching the _aliases style) -------------------


def test_dedupes_with_numeric_suffix():
    assert mint_node_id("total", {"total"}) == "total_2"
    assert mint_node_id("total", {"total", "total_2"}) == "total_3"


def test_dedupe_applies_after_sanitisation():
    # sanitised base "read_table" collides -> suffixed.
    assert mint_node_id("read table!", {"read_table"}) == "read_table_2"


# -- the four collision classes (module_collision_set) ---------------------

_SOURCE = '''\
from engine import main
from calc import total
from table import read_table as read_tbl


def helper(x: float) -> float:
    return x + 1


@main
def report(threshold: float = 0.0):
    vals = read_tbl("data.csv")
    n = len(vals)
    return total(vals)
'''


def test_collision_set_includes_call_names():
    names = module_collision_set(_SOURCE, "examples.demo")
    # imported call names (aliased import uses the local name) + local def name
    assert "total" in names
    assert "read_tbl" in names
    assert "helper" in names


def test_collision_set_includes_composite_params():
    names = module_collision_set(_SOURCE, "examples.demo")
    assert "threshold" in names


def test_collision_set_includes_existing_node_ids_and_targets():
    # passed-in graph ids AND assignment targets parsed from the body
    names = module_collision_set(_SOURCE, "examples.demo", node_ids=["already_here"])
    assert "already_here" in names
    assert "vals" in names  # a body assignment target
    assert "n" in names


def test_collision_set_includes_builtins_used_in_body():
    names = module_collision_set(_SOURCE, "examples.demo")
    assert "len" in names  # referenced by name in the composite body


# -- minting against a real module dodges each class ------------------------


def test_mint_avoids_call_name_shadow():
    # Dropping a second `total`-typed node must not be named `total` — that would
    # shadow the imported function it has to call (the wiring_lines shadow case).
    names = module_collision_set(_SOURCE, "examples.demo")
    assert mint_node_id("total", names) == "total_2"


def test_mint_avoids_composite_parameter():
    names = module_collision_set(_SOURCE, "examples.demo")
    assert mint_node_id("threshold", names) == "threshold_2"


def test_mint_avoids_builtin_used_in_body():
    names = module_collision_set(_SOURCE, "examples.demo")
    assert mint_node_id("len", names) == "len_2"


def test_mint_avoids_existing_node_id():
    names = module_collision_set(_SOURCE, "examples.demo", node_ids=["vals"])
    assert mint_node_id("vals", names) == "vals_2"


def test_extra_reserves_a_not_yet_imported_call_name():
    # A dropped type whose import W2 will add is not in the source yet; `extra`
    # lets the caller reserve its future call name so the id never shadows it.
    names = module_collision_set(_SOURCE, "examples.demo", extra=["average"])
    assert mint_node_id("average", names) == "average_2"


def test_uncontended_name_mints_cleanly_against_a_real_module():
    names = module_collision_set(_SOURCE, "examples.demo")
    assert mint_node_id("average", names) == "average"
