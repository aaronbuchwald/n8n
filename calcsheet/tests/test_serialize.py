"""The archival form: versioned, JSON-able, and lossless in both directions."""

from __future__ import annotations

import json

import pytest

from calcsheet import (
    RESULT_SCHEMA_KEY,
    RESULT_SCHEMA_VERSION,
    Calc,
    CalcError,
    Check,
    Formula,
    Input,
    Result,
)
from calcsheet.examples.capacity import build_calc


@pytest.fixture(scope="module")
def result():
    return build_calc().evaluate()


def test_the_payload_carries_a_schema_version(result):
    assert result.to_dict()[RESULT_SCHEMA_KEY] == RESULT_SCHEMA_VERSION


def test_the_payload_is_json_dumpable(result):
    text = json.dumps(result.to_dict())

    assert json.loads(text)["title"] == "Capacity check"


def test_the_round_trip_is_lossless(result):
    assert Result.from_dict(result.to_dict()) == result


def test_a_result_opts_in_to_the_host_serialisation_protocol(result):
    """A host probes `to_jsonable`; this is the explicit promise it looks for."""
    assert result.to_jsonable() == result.to_dict()


def test_the_round_trip_survives_a_trip_through_json(result):
    assert Result.from_dict(json.loads(json.dumps(result.to_dict()))) == result


def test_a_reconstructed_result_renders_the_same_card(result):
    from calcsheet import render_html

    assert render_html(Result.from_dict(result.to_dict())) == render_html(result)


def test_every_field_survives_including_the_empty_ones():
    original = Calc(
        title="round trip",
        as_of="2026-07-24",
        inputs={"a": Input(2.5, ref="src", unit="kN")},
        formulas=[Formula("b", "a * 2", ref="doubled")],
        checks=[Check("b > 1", "positive")],
        precision=5,
    ).evaluate()

    restored = Result.from_dict(original.to_dict())

    assert restored == original
    assert restored.precision == 5
    assert restored.inputs[0].unit == "kN"
    assert restored.checks[0].description == "positive"


def test_an_archive_written_before_a_check_carried_its_unit_still_reads():
    # Widening a field must not make this package refuse results it has already
    # written — the same rule the version note in `serialize` states. An old
    # payload has no `utilisation_unit`; it reads back as "" and renders the
    # unitless chip those cards always showed, at the SAME schema version.
    result = Calc(
        title="older archive",
        as_of="2026-07-24",
        inputs={"a": Input(4.0)},
        formulas=[Formula("u", "a * 10", unit="%")],
        checks=[Check("u < 100", "target", utilisation="u")],
    ).evaluate()
    payload = json.loads(json.dumps(result.to_dict()))
    for check in payload["checks"]:
        del check["utilisation_unit"]

    restored = Result.from_dict(payload)

    assert restored.checks[0].utilisation_unit == ""
    assert restored.checks[0].utilisation == result.checks[0].utilisation
    assert restored.checks[0].limit == 100.0


def test_an_unknown_schema_version_is_refused(result):
    payload = result.to_dict()
    payload[RESULT_SCHEMA_KEY] = RESULT_SCHEMA_VERSION + 1

    with pytest.raises(CalcError, match="schema version"):
        Result.from_dict(payload)


def test_a_dict_that_is_not_a_result_is_refused():
    with pytest.raises(CalcError, match=f"missing the key '{RESULT_SCHEMA_KEY}'"):
        Result.from_dict({"title": "not ours"})


def test_a_malformed_field_names_itself(result):
    payload = result.to_dict()
    payload["precision"] = "three"

    with pytest.raises(CalcError, match="precision must be a whole number"):
        Result.from_dict(payload)
