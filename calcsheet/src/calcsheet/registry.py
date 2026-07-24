"""What renderings exist — a catalogue, not the way you call them.

Authors call the free functions directly (``render_html(result, options)``):
real signature, real types, real autocomplete. This module exists for the
*other* audience — tooling that must enumerate the backends, describe what
each produces, and resolve one by name without importing any of them.

Enumeration therefore never runs a backend's ``load``: listing a renderer that
is not installed succeeds and says so; only :func:`get_renderer` imports, and
that is where a missing extra fails, with the install command in the message.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .errors import CalcError

# A renderer returns a document (str) or a binary (bytes); `options` is the
# backend's own frozen options dataclass, so the signature stays untyped here.
Renderer = Callable[..., str | bytes]


@dataclass(frozen=True)
class RendererInfo:
    """A backend describing itself without being imported.

    ``media_type`` and ``output`` are how a renderer declares what it produces
    so a UI can decide how to present it (sandboxed frame vs download).
    ``requires`` names the extra that provides the backend — ``None`` means it
    ships in core and is always available.
    """

    name: str
    media_type: str
    output: type
    options_type: type | None
    requires: str | None
    load: Callable[[], Renderer]


def _load_html() -> Renderer:
    from .render import render_html

    return render_html


def _html_options_type() -> type:
    from .render import HtmlOptions

    return HtmlOptions


# Third-party backends registered at runtime. Core entries are built by
# renderers() so importing this module pulls in no renderer at all.
_REGISTERED: list[RendererInfo] = []


def renderers() -> tuple[RendererInfo, ...]:
    """Every known renderer, installed or not. Imports no backend."""
    html = RendererInfo(
        name="html",
        media_type="text/html",
        output=str,
        options_type=_html_options_type(),
        requires=None,
        load=_load_html,
    )
    return (html, *_REGISTERED)


def register_renderer(info: RendererInfo) -> None:
    """Add a third-party backend to the catalogue.

    Optional: a third party's ``render_<name>`` is already first-class without
    this. Registering only buys enumeration and name-based resolution.
    """
    if any(existing.name == info.name for existing in renderers()):
        raise CalcError(f"renderer {info.name!r} is already registered")
    _REGISTERED.append(info)


def renderer_info(name: str) -> RendererInfo:
    """The catalogue entry for ``name``, installed or not."""
    known = renderers()
    for info in known:
        if info.name == name:
            return info
    raise CalcError(
        f"unknown renderer {name!r}; available renderers: "
        f"{', '.join(info.name for info in known)}"
    )


def get_renderer(name: str) -> Renderer:
    """Resolve ``name`` to its render function, importing the backend now.

    A backend that is listed but not installed fails *here* — at the call, not
    at import or enumeration — with the command that installs it.
    """
    info = renderer_info(name)
    try:
        return info.load()
    except ImportError as error:
        if info.requires is None:
            raise CalcError(
                f"the {info.name!r} renderer could not be imported ({error})"
            ) from error
        raise CalcError(
            f"the {info.name!r} renderer needs the {info.requires!r} extra: "
            f"uv sync --extra {info.requires}  (or: "
            f"pip install 'calcsheet[{info.requires}]') [{error}]"
        ) from error
