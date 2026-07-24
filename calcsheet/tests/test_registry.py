"""The catalogue: enumerate without importing, fail at the call with the fix."""

from __future__ import annotations

import pytest

from calcsheet import (
    CalcError,
    HtmlOptions,
    RendererInfo,
    get_renderer,
    register_renderer,
    renderer_info,
    renderers,
    render_html,
)
from calcsheet import registry
from calcsheet.examples.capacity import build_calc


@pytest.fixture(autouse=True)
def _empty_catalogue(monkeypatch):
    # Third-party registrations are global; keep each test's additions its own.
    monkeypatch.setattr(registry, "_REGISTERED", [])


def _uninstalled(name: str = "pdf") -> RendererInfo:
    def load():
        raise ModuleNotFoundError(f"No module named 'calcsheet.{name}'")

    return RendererInfo(
        name=name,
        media_type="application/pdf",
        output=bytes,
        options_type=None,
        requires=name,
        load=load,
    )


def test_the_html_renderer_declares_what_it_produces():
    (html,) = renderers()

    assert (html.name, html.media_type, html.output) == ("html", "text/html", str)
    assert html.options_type is HtmlOptions
    assert html.requires is None


def test_resolving_by_name_yields_the_free_function_authors_call():
    assert get_renderer("html") is render_html


def test_the_free_function_stays_the_api():
    # Resolving through the catalogue must be the same call, not a wrapper.
    result = build_calc().evaluate()

    assert get_renderer("html")(result) == render_html(result)


def test_an_unknown_name_lists_what_is_available():
    with pytest.raises(CalcError, match="unknown renderer 'docx'.*available.*html"):
        renderer_info("docx")


def test_enumeration_never_loads_a_backend():
    register_renderer(_uninstalled())

    # If enumeration loaded, the raising loader above would surface here.
    assert [info.name for info in renderers()] == ["html", "pdf"]
    assert renderer_info("pdf").requires == "pdf"


def test_a_missing_backend_fails_at_the_call_and_names_the_install_command():
    register_renderer(_uninstalled())

    with pytest.raises(CalcError) as failure:
        get_renderer("pdf")

    message = str(failure.value)
    assert "uv sync --extra pdf" in message
    assert "pip install 'calcsheet[pdf]'" in message


def test_a_name_may_only_be_registered_once():
    register_renderer(_uninstalled())

    with pytest.raises(CalcError, match="already registered"):
        register_renderer(_uninstalled())


def test_core_renderers_cannot_be_shadowed():
    with pytest.raises(CalcError, match="already registered"):
        register_renderer(_uninstalled("html"))
