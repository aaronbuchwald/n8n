"""Tests for the ``grouping`` pack — the contract, the registry, both strategies.

The contract is the deliverable, so it is what is tested hardest: the invariants
are exercised **for every registered strategy** (not once per implementation),
and a deliberately broken third strategy proves the enforcement is real rather
than documented.

Covers, in order:

* what a strategy is handed — population validation, and mixed units refused;
* the registry — a named lookup, an unknown name listing what exists, and a
  third strategy being an addition rather than an edit;
* the invariants, one at a time, against a strategy built to break each one;
* the invariants holding for **both** shipped strategies over the real export;
* ``single`` reproducing ``rfem.governing_force``'s 297.175507 exactly;
* ``tiered`` — the bands a threshold list defines, half-open boundary
  membership at an exact threshold, the empty-tier error, parameter validation;
* provenance surviving into each group's governing force;
* determinism and order-independence for both strategies;
* ``rfem.member_ends`` — the population node the strategies are fed from.

Run with:  uv run --extra dev --extra sym python -m pytest -q
"""

from __future__ import annotations

import random

import pytest

import grouping
import rfem
from engine import UserError
from grouping import Group, StrategyContractError
from grouping.contract import check_invariants, governing_by_magnitude
from grouping.registry import _STRATEGIES
from grouping.tiered import bands

from server.demo import example_dir

# The export the RFEM example reads, borrowed rather than copied.
EXPORT_CSV = example_dir("beam_bearing_pressure_rfem") / "export.csv"

# What the whole file is known to hold (the sanity check every test leans on).
VZ_ROWS = 184
GOVERNING_VALUE = 297.175507
GOVERNING_REF = "RFEM 10103/1578 @ 6.15 m · LK67"

# The demo's thresholds and the division they actually produce on this data.
DEMO_THRESHOLDS = [150, 50]
DEMO_DISTRIBUTION = [
    ("T1", "[150, ∞) kN", 24, 297.175507, "RFEM 10103/1578 @ 6.15 m · LK67"),
    ("T2", "[50, 150) kN", 97, 144.104507, "RFEM 10105/1933 @ 0 m · LK80"),
    ("T3", "[0, 50) kN", 63, 48.985149, "RFEM 10112/1943 @ 5.1 m · LK3"),
]

SHIPPED = {
    "single": {},
    "tiered": {"thresholds": DEMO_THRESHOLDS},
}


@pytest.fixture(scope="module")
def population() -> list[dict]:
    """The real thing: 184 ``Extremum == Vz`` rows off the committed export."""
    return rfem.member_ends(rfem.read_extrema(str(EXPORT_CSV)), component="Vz")


@pytest.fixture
def clean_registry():
    """Register test-only strategies without leaking them into other tests."""
    before = dict(_STRATEGIES)
    yield
    _STRATEGIES.clear()
    _STRATEGIES.update(before)


def force(value: float, ref: str = "", unit: str = "kN") -> dict:
    """A minimal force record — the shape every strategy is promised."""
    return {"value": value, "unit": unit, "ref": ref}


# -- what a strategy is handed -------------------------------------------------


def test_the_population_is_validated_before_any_strategy_sees_it():
    with pytest.raises(UserError, match="must be a list of force records"):
        grouping.apply_strategy("single", {"value": 1.0}, {})


def test_an_empty_population_is_refused_rather_than_grouped():
    with pytest.raises(UserError, match="population is empty"):
        grouping.apply_strategy("single", [], {})


def test_a_record_without_a_value_is_refused_naming_what_it_has():
    with pytest.raises(UserError) as caught:
        grouping.apply_strategy("single", [{"unit": "kN"}], {})
    assert "population entry 0 has no 'value' key" in str(caught.value)
    assert "'unit'" in str(caught.value)


@pytest.mark.parametrize("bad", [True, "120", None, float("inf")])
def test_a_value_that_is_not_a_finite_number_is_refused(bad):
    with pytest.raises(UserError):
        grouping.apply_strategy("single", [{"value": bad}], {})


def test_mixed_units_in_one_population_are_refused():
    """A threshold in a mixed-unit population would mean two things at once."""
    with pytest.raises(UserError, match="one population must be one unit"):
        grouping.apply_strategy(
            "single", [force(1.0, unit="kN"), force(2.0, unit="N")], {}
        )


# -- the registry --------------------------------------------------------------


def test_both_shipped_strategies_are_registered():
    assert {"single", "tiered"} <= set(grouping.strategy_names())


def test_an_unknown_strategy_lists_the_ones_that_exist():
    with pytest.raises(UserError) as caught:
        grouping.apply_strategy("tier", [force(1.0)], {})
    message = str(caught.value)
    assert "unknown grouping strategy 'tier'" in message
    for name in grouping.strategy_names():
        assert repr(name) in message
    # …and says what each one does, so the answer is in the message.
    assert "governed by the overall maximum" in message


def test_a_strategy_named_by_something_other_than_a_string_is_refused():
    with pytest.raises(UserError, match="named by a string"):
        grouping.apply_strategy(7, [force(1.0)], {})


def test_a_third_strategy_is_an_addition_not_an_edit(clean_registry):
    """Registering + using a new strategy touches no existing file's logic."""

    def by_sign(population, params):
        grouping.reject_unknown_params(params, strategy="by_sign", accepted=())
        positive = tuple(r for r in population if r["value"] > 0)
        return [
            Group(
                key="pos",
                label="every member end",
                members=positive,
                governing=governing_by_magnitude(positive),
            )
        ]

    grouping.register("by_sign", by_sign, summary="a test-only third strategy")
    assert "by_sign" in grouping.strategy_names()

    (group,) = grouping.apply_strategy("by_sign", [force(3.0), force(1.0)], {})
    assert group.key == "pos" and group.count == 2
    # It goes through the same front door: its params are policed too.
    with pytest.raises(UserError, match="does not take 'thresholds'"):
        grouping.apply_strategy("by_sign", [force(3.0)], {"thresholds": [1]})


def test_registering_a_different_callable_under_a_taken_name_is_refused(clean_registry):
    with pytest.raises(ValueError, match="already registered"):
        grouping.register("single", lambda population, params: [])


# -- the invariants, one at a time --------------------------------------------
#
# `check_invariants` is called directly here rather than through a registered
# strategy: the point is the enforcement, and each case names exactly which
# clause of the contract it violates.


def _population(n: int = 3) -> list[dict]:
    return [force(float(i + 1), ref=f"row-{i}") for i in range(n)]


def test_invariant_1_a_dropped_member_end_is_caught():
    people = _population()
    groups = [Group("a", "a", tuple(people[:2]), people[0])]
    with pytest.raises(StrategyContractError, match="fell in no group at all"):
        check_invariants(groups, people, strategy="broken")


def test_invariant_2_a_member_end_in_two_groups_is_caught():
    people = _population()
    groups = [
        Group("a", "a", tuple(people), people[0]),
        Group("b", "b", (people[0],), people[0]),
    ]
    with pytest.raises(StrategyContractError, match="lands in 2 groups"):
        check_invariants(groups, people, strategy="broken")


def test_invariant_3_an_empty_group_is_caught():
    people = _population()
    groups = [Group("a", "a", tuple(people), people[0]), Group("b", "b", (), people[0])]
    with pytest.raises(StrategyContractError, match="is empty"):
        check_invariants(groups, people, strategy="broken")


def test_invariant_4_a_governing_record_that_is_not_a_member_is_caught():
    """This is what makes provenance impossible to fake."""
    people = _population()
    invented = force(999.0, ref="invented")
    groups = [Group("a", "a", tuple(people), invented)]
    with pytest.raises(StrategyContractError, match="not one of its own members"):
        check_invariants(groups, people, strategy="broken")


def test_invariant_4_rejects_an_equal_but_different_record():
    """Identity, not equality: a *copy* of a member is still not that member."""
    people = _population()
    twin = dict(people[0])
    groups = [Group("a", "a", tuple(people), twin)]
    with pytest.raises(StrategyContractError, match="not one of its own members"):
        check_invariants(groups, people, strategy="broken")


def test_invariant_5_a_key_that_is_not_an_identifier_is_caught():
    people = _population()
    groups = [Group("[150, inf)", "a", tuple(people), people[0])]
    with pytest.raises(StrategyContractError, match="not a valid identifier"):
        check_invariants(groups, people, strategy="broken")


def test_invariant_5_duplicate_keys_are_caught():
    people = _population(2)
    groups = [
        Group("a", "a", (people[0],), people[0]),
        Group("a", "a", (people[1],), people[1]),
    ]
    with pytest.raises(StrategyContractError, match="share the key"):
        check_invariants(groups, people, strategy="broken")


def test_a_record_the_strategy_invented_is_caught():
    people = _population()
    groups = [Group("a", "a", (*people, force(1.0)), people[0])]
    with pytest.raises(StrategyContractError, match="not in the population"):
        check_invariants(groups, people, strategy="broken")


def test_returning_no_groups_at_all_is_caught():
    with pytest.raises(StrategyContractError, match="returned no groups"):
        check_invariants([], _population(), strategy="broken")


def test_a_contract_violation_is_not_a_user_error(clean_registry):
    """The user cannot fix it by editing a threshold, so it is not their error."""

    def loses_one(population, params):
        kept = tuple(population[:-1])
        return [Group("a", "a", kept, governing_by_magnitude(kept))]

    grouping.register("loses_one", loses_one)
    with pytest.raises(StrategyContractError) as caught:
        grouping.apply_strategy("loses_one", _population(), {})
    assert not isinstance(caught.value, UserError)
    assert "grouping strategy 'loses_one' broke its contract" in str(caught.value)


# -- the invariants hold for BOTH shipped strategies ---------------------------


@pytest.mark.parametrize("name,params", sorted(SHIPPED.items()))
def test_a_shipped_strategy_partitions_the_real_population(name, params, population):
    groups = grouping.apply_strategy(name, population, params)

    assert sum(g.count for g in groups) == VZ_ROWS
    placed = [id(m) for g in groups for m in g.members]
    assert len(placed) == len(set(placed)) == VZ_ROWS  # total and exclusive
    assert set(placed) == {id(r) for r in population}


@pytest.mark.parametrize("name,params", sorted(SHIPPED.items()))
def test_a_shipped_strategy_returns_only_non_empty_identifier_keyed_groups(
    name, params, population
):
    groups = grouping.apply_strategy(name, population, params)

    assert groups
    assert all(g.count > 0 for g in groups)
    keys = [g.key for g in groups]
    assert len(set(keys)) == len(keys)
    assert all(key.isidentifier() for key in keys)


@pytest.mark.parametrize("name,params", sorted(SHIPPED.items()))
def test_a_shipped_strategy_governs_by_one_of_its_own_members(name, params, population):
    for group in grouping.apply_strategy(name, population, params):
        assert any(member is group.governing for member in group.members)
        assert group.governing["value"] == max(m["value"] for m in group.members)


@pytest.mark.parametrize("name,params", sorted(SHIPPED.items()))
def test_a_shipped_strategy_is_deterministic(name, params, population):
    once = grouping.apply_strategy(name, population, params)
    twice = grouping.apply_strategy(name, population, params)
    assert [(g.key, g.label, g.count, g.governing["ref"]) for g in once] == [
        (g.key, g.label, g.count, g.governing["ref"]) for g in twice
    ]


@pytest.mark.parametrize("name,params", sorted(SHIPPED.items()))
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_a_shipped_strategy_is_order_independent(name, params, population, seed):
    """Shuffling the export changes nothing — including which record governs."""
    shuffled = list(population)
    random.Random(seed).shuffle(shuffled)

    def summary(groups):
        return [
            (g.key, g.label, g.count, g.governing["value"], g.governing["ref"])
            for g in groups
        ]

    assert summary(grouping.apply_strategy(name, shuffled, params)) == summary(
        grouping.apply_strategy(name, population, params)
    )


def test_the_tie_break_does_not_depend_on_order():
    """Two equal maxima: `max()` would pick by position, this must not."""
    first = force(10.0, ref="b")
    second = force(10.0, ref="a")
    assert governing_by_magnitude([first, second]) is second
    assert governing_by_magnitude([second, first]) is second


@pytest.mark.parametrize("name,params", sorted(SHIPPED.items()))
def test_a_shipped_strategy_carries_provenance_into_every_governing_force(
    name, params, population
):
    """The card cites a real export row, per group, because this holds."""
    for group in grouping.apply_strategy(name, population, params):
        governing = group.governing
        assert governing["unit"] == "kN"
        assert governing["ref"].startswith("RFEM ")
        assert governing["component"] == "Vz"
        assert governing["source"] == "export.csv"
        for field in ("member", "node", "position", "load_case"):
            assert governing[field] is not None
        # The magnitude and its sign are both still there.
        assert governing["value"] == abs(governing["signed"])


# -- single --------------------------------------------------------------------


def test_single_reproduces_the_governing_force_exactly(population):
    """The strategy that ships today comes out of the abstraction unchanged."""
    (group,) = grouping.apply_strategy("single", population, {})

    assert group.key == "all"
    assert group.count == VZ_ROWS
    assert group.governing["value"] == GOVERNING_VALUE
    assert group.governing["ref"] == GOVERNING_REF
    # …and it is the very record `rfem.governing_force` picks.
    direct = rfem.governing_force(rfem.read_extrema(str(EXPORT_CSV)), component="Vz")
    assert group.governing == direct


def test_single_takes_no_parameters():
    with pytest.raises(UserError) as caught:
        grouping.apply_strategy("single", [force(1.0)], {"thresholds": [1]})
    assert "does not take 'thresholds'" in str(caught.value)
    assert "(no parameters)" in str(caught.value)


# -- tiered --------------------------------------------------------------------


def test_n_thresholds_define_n_plus_one_half_open_bands():
    assert bands([150, 50]) == [(150, float("inf")), (50, 150), (0.0, 50)]
    assert bands([100]) == [(100, float("inf")), (0.0, 100)]


def test_a_value_exactly_on_a_threshold_falls_in_the_upper_tier():
    """`600` belongs to [600, ∞) and `400.0` to [400, 600), never below."""
    people = [force(700.0, "big"), force(600.0, "on-600"), force(400.0, "on-400"), force(399.0, "under")]
    t1, t2, t3 = grouping.apply_strategy("tiered", people, {"thresholds": [600, 400]})

    assert [m["ref"] for m in t1.members] == ["big", "on-600"]
    assert [m["ref"] for m in t2.members] == ["on-400"]
    assert [m["ref"] for m in t3.members] == ["under"]
    assert (t1.label, t2.label, t3.label) == (
        "[600, ∞) kN",
        "[400, 600) kN",
        "[0, 400) kN",
    )


def test_an_empty_tier_is_an_error_naming_the_tier_and_its_bounds(population):
    """The brief's own 600/400 example: this data reaches neither."""
    with pytest.raises(UserError) as caught:
        grouping.apply_strategy("tiered", population, {"thresholds": [600, 400]})
    message = str(caught.value)
    assert "tier T1 [600, ∞) kN catches no member end" in message
    # It says what the data *does* span, so the fix is in the message.
    assert "297.176 kN" in message and "0.677614 kN" in message
    assert "3 connection types into 2" in message


def test_an_empty_tier_in_the_middle_is_an_error_too():
    people = [force(700.0), force(100.0)]
    with pytest.raises(UserError, match=r"tier T2 \[400, 600\) kN catches no member end"):
        grouping.apply_strategy("tiered", people, {"thresholds": [600, 400]})


def test_tiered_needs_thresholds():
    with pytest.raises(UserError) as caught:
        grouping.apply_strategy("tiered", [force(1.0)], {})
    assert "needs a 'thresholds' parameter" in str(caught.value)


def test_thresholds_must_be_declared_descending():
    with pytest.raises(UserError) as caught:
        grouping.apply_strategy("tiered", [force(1.0)], {"thresholds": [50, 150]})
    assert "must be declared descending" in str(caught.value)
    assert "not sorted for you" in str(caught.value)


def test_equal_thresholds_are_refused():
    with pytest.raises(UserError, match="must be declared descending"):
        grouping.apply_strategy("tiered", [force(1.0)], {"thresholds": [100, 100]})


@pytest.mark.parametrize("bad", [0, -5, "150", True, float("nan")])
def test_a_threshold_that_is_not_a_positive_finite_number_is_refused(bad):
    with pytest.raises(UserError):
        grouping.apply_strategy("tiered", [force(1.0)], {"thresholds": [bad]})


def test_an_empty_threshold_list_points_at_the_single_strategy():
    with pytest.raises(UserError) as caught:
        grouping.apply_strategy("tiered", [force(1.0)], {"thresholds": []})
    assert "'single' strategy" in str(caught.value)


def test_a_misspelled_parameter_is_refused_rather_than_ignored():
    """Ignoring it would leave `tiered` with no thresholds and no complaint."""
    with pytest.raises(UserError) as caught:
        grouping.apply_strategy("tiered", [force(1.0)], {"threshold": [150]})
    assert "does not take 'threshold'" in str(caught.value)
    assert "it accepts: 'thresholds'" in str(caught.value)


def test_a_negative_magnitude_is_refused_with_a_hint_about_signed():
    with pytest.raises(UserError) as caught:
        grouping.apply_strategy(
            "tiered", [force(200.0), force(-5.0, "neg")], {"thresholds": [150]}
        )
    assert "'signed' companion keeps the sign" in str(caught.value)


def test_tiered_carries_its_numeric_bounds_beside_the_label():
    t1, t2 = grouping.apply_strategy(
        "tiered", [force(700.0), force(100.0)], {"thresholds": [600]}
    )
    assert t1.extra == {"lower": 600.0, "upper": None, "unit": "kN"}
    assert t2.extra == {"lower": 0.0, "upper": 600.0, "unit": "kN"}


def test_the_demo_thresholds_divide_this_export_as_documented(population):
    groups = grouping.apply_strategy(
        "tiered", population, {"thresholds": DEMO_THRESHOLDS}
    )
    assert [
        (g.key, g.label, g.count, g.governing["value"], g.governing["ref"])
        for g in groups
    ] == DEMO_DISTRIBUTION


# -- the node ------------------------------------------------------------------


def test_the_node_returns_one_record_describing_the_whole_division(population):
    record = grouping.group(
        population, {"strategy": "tiered", "params": {"thresholds": DEMO_THRESHOLDS}}
    )

    assert record["strategy"] == "tiered"
    assert record["params"] == {"thresholds": DEMO_THRESHOLDS}
    assert record["unit"] == "kN" and record["count"] == VZ_ROWS
    assert [g["key"] for g in record["groups"]] == ["T1", "T2", "T3"]
    assert [g["count"] for g in record["groups"]] == [24, 97, 63]


def test_the_nodes_output_keeps_every_member_end_auditable(population):
    """The refs let a reader check the partition by hand from the artifact."""
    record = grouping.group(
        population, {"strategy": "tiered", "params": {"thresholds": DEMO_THRESHOLDS}}
    )
    refs = [ref for g in record["groups"] for ref in g["member_refs"]]
    assert len(refs) == VZ_ROWS == len(set(refs))  # each end named exactly once
    assert GOVERNING_REF in record["groups"][0]["member_refs"]
    assert set(refs) == {end["ref"] for end in population}


def test_the_nodes_output_is_plain_json(population):
    import json

    record = grouping.group(population, {"strategy": "single"})
    # `allow_nan=False`: an unbounded tier must not reach the artifact as the
    # non-standard `Infinity` literal.
    round_tripped = json.loads(json.dumps(record, allow_nan=False))
    assert round_tripped["groups"][0]["governing"]["value"] == GOVERNING_VALUE

    tiered = grouping.group(
        population, {"strategy": "tiered", "params": {"thresholds": DEMO_THRESHOLDS}}
    )
    assert json.loads(json.dumps(tiered, allow_nan=False))["groups"][0]["extra"][
        "upper"
    ] is None


def test_params_may_be_omitted_for_a_strategy_that_takes_none(population):
    assert grouping.group(population, {"strategy": "single"})["params"] == {}


def test_a_config_without_a_strategy_key_lists_the_strategies(population):
    with pytest.raises(UserError) as caught:
        grouping.group(population, {"params": {"thresholds": [150]}})
    assert "has no 'strategy' key" in str(caught.value)
    assert "'tiered'" in str(caught.value)


def test_a_flattened_config_is_refused_pointing_at_params(population):
    """Parameters live under 'params' — the strategy's own namespace."""
    with pytest.raises(UserError) as caught:
        grouping.group(population, {"strategy": "tiered", "thresholds": [150]})
    assert "unexpected key(s) 'thresholds'" in str(caught.value)
    assert "go inside 'params'" in str(caught.value)


def test_a_config_that_is_not_an_object_is_refused(population):
    with pytest.raises(UserError, match="must be a grouping config object"):
        grouping.group(population, "tiered")


# -- rfem.member_ends, the population the strategies are fed -------------------


def test_member_ends_keeps_every_row_the_governing_force_filter_keeps(population):
    assert len(population) == VZ_ROWS
    assert all(record["component"] == "Vz" for record in population)


def test_member_ends_and_governing_force_agree_on_the_winner(population):
    direct = rfem.governing_force(rfem.read_extrema(str(EXPORT_CSV)), component="Vz")
    assert max(population, key=lambda r: r["value"]) == direct


def test_member_ends_records_are_the_envelope_the_sheet_pack_unwraps(population):
    record = population[0]
    assert set(record) == {
        "value", "unit", "ref", "component", "signed",
        "member", "node", "position", "load_case", "source",
    }


def test_member_ends_refuses_the_same_things_governing_force_refuses():
    table = rfem.read_extrema(str(EXPORT_CSV))
    with pytest.raises(UserError, match="unknown component 'My'"):
        rfem.member_ends(table, component="My")
    with pytest.raises(UserError, match="must be an RFEM extrema table"):
        rfem.member_ends("not a table", component="Vz")
