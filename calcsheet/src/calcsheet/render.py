"""Result -> a self-contained HTML card.

Inline CSS only, native MathML for the math, no scripts, no web fonts, no
network of any kind — the file can be mailed, archived or opened offline in
ten years and still look like itself. Every string that came from the caller
is HTML-escaped; every string that is markup is checked by the guard in
:mod:`calcsheet.mathml` before it is embedded.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from .errors import CalcError
from .evaluate import CheckResult, Result, Row, format_value
from .mathml import assert_plain_mathml

# The card is a DOCUMENT, so its default ramp is a document's: white paper,
# black ink. Three greys carry everything below the ink — `--muted` for prose
# that is still text (units, descriptions, the verdict line), `--faint` for the
# apparatus an eye should skip until it wants it (the `=` glyphs, section
# labels, code references). Both clear WCAG AA on white, which the old
# `--faint:#98a1b3` (2.4:1) did not.
#
# `--line` divides the card's own parts; `--rule` draws its outer boundary.
# Keeping them separate is what lets a white card sit on a white page without
# a grey backdrop faking the separation — see `.card` below.
_LIGHT_VARS = """
:root{
  --bg:#fff; --card:#fff; --ink:#000; --muted:#3d4450; --faint:#6b7280;
  --line:#e4e4e7; --rule:#b4bbc6;
  --pass:#14532d; --pass-soft:#ecfdf3; --fail:#991b1b; --fail-soft:#fef2f2;
  --mono:"SF Mono",ui-monospace,Menlo,Consolas,monospace;
  --sans:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
}
"""

# One source for the dark ramp, emitted either behind the media query (theme
# "auto") or unconditionally (theme "dark") — never duplicated.
_DARK_VARS = """  --bg:#0e1117; --card:#161b24; --ink:#e7ecf3; --muted:#95a0b2; --faint:#67728a;
  --line:#252c39; --rule:#333c4d; --pass:#4cc17f; --pass-soft:#122a1c;
  --fail:#f0776b; --fail-soft:#2a1512;
"""
_DARK_MEDIA = "@media (prefers-color-scheme:dark){:root{\n" + _DARK_VARS + "}}\n"
_DARK_ALWAYS = ":root{\n" + _DARK_VARS + "}\n"

# FOUR TYPE ROLES, and nothing else gets a size of its own:
#   title      17px sans   — the sheet's heading, once at the top
#   content    14px mono   — every number, symbol and equation an engineer reads
#   annotation 11.5px      — provenance and prose about the content (refs,
#                            as-of, check descriptions, the verdict line)
#   label      10px mono   — uppercase apparatus (section labels, verdict chips)
# The old card spent eight sizes on these four jobs, which made a check's
# equation (13.5px) read as a lesser thing than the identical equation in the
# rows above it (14px). One size per role means size now means something.
_BASE_CSS = """*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
     line-height:1.5;padding:28px}
.wrap{max-width:760px;margin:0 auto}

/* White card on a white page: the boundary is DRAWN, not implied by a grey
   backdrop. `--rule` is the card's own edge and travels with it — into a PDF,
   a print, an email client that drops shadows — where a tinted page would
   only bleed. The shadow is a second, screen-only cue, never the only one. */
.card{background:var(--card);border:1px solid var(--rule);border-radius:8px;
      overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.card__head{display:flex;align-items:center;gap:12px;padding:16px 20px;
            border-bottom:1px solid var(--line)}
.card__title{font-size:17px;font-weight:650;margin:0;flex:1;letter-spacing:-.005em}
.card__asof{font-family:var(--mono);font-size:11.5px;color:var(--faint)}
/* PASS/FAIL must survive greyscale, so the verdict is carried by the WORD and
   by a distinct glyph (check vs cross). Colour is the third cue, never the
   first — the old card used one identical dot for both. */
.status{font-family:var(--mono);font-size:10px;font-weight:700;letter-spacing:.1em;
        padding:4px 10px;border-radius:100px;white-space:nowrap;border:1px solid}
.status--fail{background:var(--fail-soft);color:var(--fail);border-color:var(--fail)}
.status--pass{background:var(--pass-soft);color:var(--pass);border-color:var(--pass)}

.sec{padding:14px 20px;overflow-x:auto}
.sec+.sec{border-top:1px solid var(--line)}
.sec__label{font-family:var(--mono);font-size:10px;text-transform:uppercase;
            letter-spacing:.14em;color:var(--faint);margin:0 0 10px}

/* The SECTION is the horizontal scrollport and the grid inside it takes
   min-width:max-content — they must be DIFFERENT elements, or the "scroll
   container" just grows and its parent clips instead. Content must never be
   unreachable.

   BASELINE, not centre, and it earns its keep now that a row with a fraction is
   half again as tall as one without: baseline puts the symbol, both `=` glyphs
   and the value on the fraction's own bar (measured: 1.3px off it), where an
   engineer reads them. Centring would put them on the middle of the equation's
   BOUNDING BOX instead, which drifts off the bar the moment a fraction is
   lopsided — a nested numerator over a bare denominator moves it 3.2px down. */
.rows{display:grid;row-gap:11px;column-gap:10px;align-items:baseline;
      min-width:max-content;font-family:var(--mono);font-size:14px}
/* Two row types, two templates, because they need their slack in different
   places. A formula spends width on its definition, so the 1fr sits there:
   sym = definition ........ = value+unit | ref.
   A given HAS no definition, and putting the slack mid-row flung its value to
   the far edge, a screen away from the symbol it belongs to. So a given gets
   no definition slot at all and its slack moves behind the value:
   sym = value+unit ........ | ref — one phrase, left, as the sheet prints it. */
.rows--calc{grid-template-columns:auto auto 1fr auto minmax(4.5rem,auto) auto}
.rows--given{grid-template-columns:auto auto auto 1fr}
/* Symbols right-align so every `=` stacks in one vertical line down a section
   — the alignment the engineering sheet this mirrors uses. */
.sym{text-align:right}
.eq{color:var(--faint)}
/* No scroller of its own: an equation is read whole or not at all, so the row
   simply grows to it and `.sec` stays the one horizontal scrollport for a
   viewport too narrow for the grid. */
.def{white-space:nowrap}
.val{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
/* A given's value is the start of a phrase, not the end of a column, so it
   sets from the `=` rather than back from the right edge. */
.rows--given .val{text-align:left}
.unit{color:var(--muted);font-style:normal}
.ref{justify-self:end;font-family:var(--sans);font-size:11.5px;color:var(--faint);
     white-space:nowrap;padding-left:14px;border-left:1px solid var(--line)}
math{font-size:1em}
/* A definition and a check are DISPLAYED equations, and their markup says so
   (`display="block"` — see `calcsheet.mathml`). That is what typesets a
   fraction at full size; under MathML's inline style every nested level is
   0.71em, so `f_c90k·k_mod / γ_M` read 9.9px against the row's 14px.
   `display="block"` also asks for a block-level, centred BOX, which a cell in a
   four-slot row does not want — so only the box is put back on the row's line
   here. The display STYLE is a separate property and is untouched by this, and
   a browser too old to know `inline math` merely lays the full-size equation
   out as its own block. Height is deliberately not constrained anywhere on this
   path: the cell, the row and the card each grow to whatever the equation
   needs. */
.def math,.chk__eq math{display:inline math}

.checks{display:grid;gap:8px}
.chk{display:grid;grid-template-columns:1fr auto auto;align-items:center;gap:12px;
     padding:9px 12px;border:1px solid var(--line);border-radius:8px;
     min-width:max-content}
/* A failing check reads as failing with the colour removed: heavier leading
   edge (weight is form), plus the cross glyph and the word in its badge. */
.chk--fail{border-left:3px solid var(--fail);padding-left:10px}
.chk__eq{font-family:var(--mono);font-size:14px}
.chk__bool{font-family:var(--mono);font-size:11.5px;color:var(--muted);
           font-variant-numeric:tabular-nums;white-space:nowrap}
.chk__what{display:block;font-family:var(--sans);font-size:11.5px;color:var(--muted);
           margin-top:2px}
.badge{font-family:var(--mono);font-size:10px;font-weight:700;letter-spacing:.1em;
       padding:3px 9px;border-radius:6px;border:1px solid;white-space:nowrap}
.badge--pass{background:var(--pass-soft);color:var(--pass);border-color:var(--pass)}
.badge--fail{background:var(--fail-soft);color:var(--fail);border-color:var(--fail)}

.foot{padding:12px 20px;border-top:1px solid var(--line);font-size:11.5px;
      color:var(--muted)}
.foot b{color:var(--ink)}
"""

# Appended only when a slot is actually filled, so an options-free render stays
# byte-identical to the card this package has always emitted.
_SLOT_CSS = """.card__banner{padding:10px 20px;border-bottom:1px solid var(--line);
              font-family:var(--mono);font-size:11px;letter-spacing:.08em;
              text-transform:uppercase;color:var(--faint)}
.foot--note{background:none;border-top:1px dashed var(--line);color:var(--faint);
            font-size:11.5px}
"""

# Same rule as the slots: only calcs that report a utilisation pay for the
# fourth chip column. `.chk--util` follows `.chk`, so the override wins.
_UTILISATION_CSS = """.chk--util{grid-template-columns:1fr auto auto auto}
.chk__util{font-family:var(--mono);font-size:14px;font-weight:700;
           font-variant-numeric:tabular-nums;white-space:nowrap}
"""

_THEMES = {"auto": _DARK_MEDIA, "light": "", "dark": _DARK_ALWAYS}


@dataclass(frozen=True)
class HtmlOptions:
    """Knobs for :func:`render_html` — presentation only, never the numbers.

    Field names (``theme``, ``header``, ``footer``) are shared by convention
    with any future renderer's own options type; there is deliberately no
    shared superset, so no backend has to police another's knobs. All fields
    are scalars, so the whole thing round-trips JSON as a graph literal.

    ``header`` is a banner above the card head; ``footer`` is the notes slot
    under the verdict line — fine print such as source pins or a code edition.

    ``theme`` defaults to ``"light"``: a card is a document, and a document is
    white paper with black ink whoever opens it. ``"auto"`` (follow the
    viewer's OS) and ``"dark"`` remain available and are worth keeping — the
    card may be handed to another viewer or a PDF path later, so the choice
    should be stated in the file rather than inferred from wherever it lands.
    """

    theme: str = "light"
    header: str = ""
    footer: str = ""

    def __post_init__(self) -> None:
        if self.theme not in _THEMES:
            raise CalcError(
                f"unknown theme {self.theme!r}; available themes: "
                f"{', '.join(sorted(_THEMES))}"
            )


def _stylesheet(
    options: HtmlOptions, *, with_slots: bool, with_utilisation: bool
) -> str:
    css = _LIGHT_VARS + _THEMES[options.theme] + _BASE_CSS
    if with_slots:
        css += _SLOT_CSS
    if with_utilisation:
        css += _UTILISATION_CSS
    return css


def _verdict(passed: bool) -> str:
    return "PASS" if passed else "FAIL"


# The verdict's glyph, so PASS and FAIL differ in FORM and not only in colour.
# CHECK MARK / BALLOT X, both present in the system sans of every platform the
# card's font stack names — no web font, nothing to fetch. It TRAILS the word:
# the word is the verdict, the glyph only seconds it.
_VERDICT_GLYPH = {True: "&#10003;", False: "&#10007;"}


def _verdict_label(passed: bool) -> str:
    """``PASS ✓`` / ``FAIL ✗`` — the word first, then its glyph."""
    return f"{_verdict(passed)} {_VERDICT_GLYPH[passed]}"


def _row_html(row: Row, *, with_definition: bool) -> str:
    """One row.

    A **formula** keeps all four slots — ``sym = definition = value+unit`` and
    its reference — with the slack in the definition column.

    A **given** has no right-hand side, so it gets no definition slot at all:
    ``sym = value+unit``, read as one phrase at the left, with the slack moved
    behind it so the reference still lands at the far edge. Value and unit stay
    inside the one ``.val`` span exactly as a formula's do, so an empty given is
    still ``– mm`` with its reference intact.
    """
    assert_plain_mathml(row.symbol_mathml)
    unit = f'&nbsp;<span class="unit">{escape(row.unit)}</span>' if row.unit else ""
    value = f'<span class="val">{escape(row.value_text)}{unit}</span>'
    reference = (
        f'<span class="ref">{escape(row.ref)}</span>' if row.ref else "<span></span>"
    )
    symbol = f'<span class="sym">{row.symbol_mathml}</span><span class="eq">=</span>'
    if not with_definition:
        return f"{symbol}{value}{reference}"
    if row.definition_mathml:
        assert_plain_mathml(row.definition_mathml)
    return (
        f"{symbol}"
        f'<span class="def">{row.definition_mathml}</span>'
        f'<span class="eq">=</span>'
        f"{value}{reference}"
    )


def _section_html(label: str, rows: tuple[Row, ...], *, with_definition: bool) -> str:
    # The two row types are already separate sections, so each grid can carry
    # the template its own rows need — see `.rows--calc` / `.rows--given`.
    grid = "rows rows--calc" if with_definition else "rows rows--given"
    body = "\n        ".join(
        _row_html(row, with_definition=with_definition) for row in rows
    )
    return (
        '    <div class="sec">\n'
        f'      <p class="sec__label">{escape(label)}</p>\n'
        f'      <div class="{grid}">\n'
        f"        {body}\n"
        "      </div>\n"
        "    </div>"
    )


def _margin_text(check: CheckResult, precision: int) -> str:
    """``0.759 ≤ 0.833`` — the margin an engineer reads instead of PASS.

    ``≤`` is the utilisation relation itself ("must not exceed the limit"),
    not the check's operator; the exact operator and numbers sit alongside in
    the substituted string.
    """
    utilisation = format_value(check.utilisation, precision)
    if check.limit is None:
        return utilisation
    return f"{utilisation} ≤ {format_value(check.limit, precision)}"


def _check_html(check: CheckResult, precision: int) -> str:
    assert_plain_mathml(check.expr_mathml)
    verdict = _verdict(check.passed).lower()
    description = (
        f'<span class="chk__what">{escape(check.description)}</span>'
        if check.description
        else ""
    )
    margin = (
        f'          <span class="chk__util">'
        f"{escape(_margin_text(check, precision))}</span>\n"
        if check.utilisation is not None
        else ""
    )
    classes = ["chk"]
    if margin:
        classes.append("chk--util")
    if not check.passed:
        classes.append("chk--fail")
    return (
        f'        <div class="{" ".join(classes)}">\n'
        f'          <div><span class="chk__eq">{check.expr_mathml}</span>'
        f"{description}</div>\n"
        f"{margin}"
        f'          <span class="chk__bool">{escape(check.substituted)}</span>\n'
        f'          <span class="badge badge--{verdict}">'
        f"{_verdict_label(check.passed)}</span>\n"
        "        </div>"
    )


def _checks_html(checks: tuple[CheckResult, ...], precision: int) -> str:
    body = "\n".join(_check_html(check, precision) for check in checks)
    return (
        '    <div class="sec">\n'
        '      <p class="sec__label">Design checks</p>\n'
        '      <div class="checks">\n'
        f"{body}\n"
        "      </div>\n"
        "    </div>"
    )


def render_html(result: Result, options: HtmlOptions | None = None) -> str:
    """Render ``result`` as a complete, self-contained HTML document.

    Deterministic by construction: everything drawn here comes from the one
    :class:`~calcsheet.evaluate.Result` plus the caller's ``options``, so the
    same pair renders byte-identical output every time. Omitting ``options``
    renders exactly the card this package has always emitted.
    """
    options = options or HtmlOptions()
    banner = (
        f'    <div class="card__banner">{escape(options.header)}</div>\n'
        if options.header
        else ""
    )
    note = (
        f'\n    <div class="foot foot--note">{escape(options.footer)}</div>'
        if options.footer
        else ""
    )
    with_utilisation = any(check.utilisation is not None for check in result.checks)
    stylesheet = _stylesheet(
        options, with_slots=bool(banner or note), with_utilisation=with_utilisation
    )

    governing = ""
    if result.governing is not None:
        expr, utilisation = result.governing
        governing = (
            f"\n      Governing check <b>{escape(expr)}</b> at "
            f"<b>{escape(format_value(utilisation, result.precision))}</b>."
        )

    verdict = _verdict(result.passed)
    sections = []
    if result.inputs:
        sections.append(_section_html("Inputs", result.inputs, with_definition=False))
    if result.formulas:
        sections.append(
            _section_html("Calculation", result.formulas, with_definition=True)
        )
    if result.checks:
        sections.append(_checks_html(result.checks, result.precision))
    body = "\n\n".join(sections)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(result.title)} — {escape(result.as_of)}</title>
<style>{stylesheet}</style>
</head>
<body>
<div class="wrap">
  <div class="card">
{banner}    <div class="card__head">
      <h1 class="card__title">{escape(result.title)}</h1>
      <span class="card__asof">AS_OF {escape(result.as_of)}</span>
      <span class="status status--{verdict.lower()}">{_verdict_label(result.passed)}</span>
    </div>

{body}

    <div class="foot">
      Overall <b>{verdict}</b> — a calc is valid only when <b>every</b> check passes.{governing}
    </div>{note}
  </div>
</div>
</body>
</html>
"""
