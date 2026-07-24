"""Result -> a self-contained HTML card.

Inline CSS only, native MathML for the math, no scripts, no web fonts, no
network of any kind — the file can be mailed, archived or opened offline in
ten years and still look like itself. Every string that came from the caller
is HTML-escaped; every string that is markup is checked by the guard in
:mod:`calcsheet.mathml` before it is embedded.
"""

from __future__ import annotations

from html import escape

from .evaluate import CheckResult, Result, Row
from .mathml import assert_plain_mathml

# Adapted from the owner-approved strawman. Light and dark are the same design
# with a swapped ramp; values use tabular numerals so columns of digits line up.
_CSS = """
:root{
  --bg:#f6f7f9; --card:#fff; --ink:#1a2130; --muted:#6b7688; --faint:#98a1b3;
  --line:#e2e6ec; --rule:#c9d0da;
  --pass:#1f8a4c; --pass-soft:#e7f4ec; --fail:#c33a2e; --fail-soft:#fdeceb;
  --mono:"SF Mono",ui-monospace,Menlo,Consolas,monospace;
  --sans:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
}
@media (prefers-color-scheme:dark){:root{
  --bg:#0e1117; --card:#161b24; --ink:#e7ecf3; --muted:#95a0b2; --faint:#67728a;
  --line:#252c39; --rule:#333c4d; --pass:#4cc17f; --pass-soft:#122a1c;
  --fail:#f0776b; --fail-soft:#2a1512;
}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
     line-height:1.5;padding:28px}
.wrap{max-width:760px;margin:0 auto}

.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
      overflow:hidden;box-shadow:0 1px 2px rgba(20,30,50,.05)}
.card__head{display:flex;align-items:center;gap:12px;padding:16px 20px;
            border-bottom:1px solid var(--line)}
.card__title{font-size:16px;font-weight:680;margin:0;flex:1}
.card__asof{font-family:var(--mono);font-size:11.5px;color:var(--faint)}
.status{font-family:var(--mono);font-size:11px;font-weight:700;letter-spacing:.04em;
        padding:4px 10px;border-radius:100px;white-space:nowrap}
.status--fail{background:var(--fail-soft);color:var(--fail)}
.status--pass{background:var(--pass-soft);color:var(--pass)}

.sec{padding:14px 20px;overflow-x:auto}
.sec+.sec{border-top:1px solid var(--line)}
.sec__label{font-family:var(--mono);font-size:10px;text-transform:uppercase;
            letter-spacing:.14em;color:var(--faint);margin:0 0 10px}

/* the four-slot rows: symbol = definition = value+unit ... reference */
/* Rows and checks keep their cells on one line, so in a narrow container (a node
   card on a canvas) they are wider than the box. The SECTION is the scrollport
   and the grid inside it takes `min-width:max-content` — they must be different
   elements, or the "scroll container" simply grows and its parent clips instead.
   Content must never be unreachable. */
.rows{display:grid;grid-template-columns:auto auto 1fr auto minmax(4.5rem,auto) auto;
      row-gap:12px;column-gap:10px;align-items:baseline;min-width:max-content;
      font-family:var(--mono);font-size:14px}
.sym{text-align:right}
.eq{color:var(--faint)}
.def{white-space:nowrap;overflow-x:auto}
.val{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.unit{color:var(--muted);font-style:normal}
.ref{justify-self:end;font-family:var(--sans);font-size:11.5px;color:var(--faint);
     white-space:nowrap;padding-left:14px;border-left:1px solid var(--line)}
math{font-size:1em}

.checks{display:grid;gap:8px}
.chk{display:grid;grid-template-columns:1fr auto auto;align-items:center;gap:12px;
     padding:9px 12px;border:1px solid var(--line);border-radius:8px;
     min-width:max-content}
.chk__eq{font-family:var(--mono);font-size:13.5px}
.chk__bool{font-family:var(--mono);font-size:12px;color:var(--muted);
           font-variant-numeric:tabular-nums;white-space:nowrap}
.chk__what{display:block;font-family:var(--sans);font-size:11.5px;color:var(--muted);
           margin-top:2px}
.badge{font-family:var(--mono);font-size:11px;font-weight:700;letter-spacing:.03em;
       padding:3px 9px;border-radius:6px}
.badge--pass{background:var(--pass-soft);color:var(--pass)}
.badge--fail{background:var(--fail-soft);color:var(--fail)}

.foot{padding:12px 20px;border-top:1px solid var(--line);font-size:12px;
      color:var(--muted);background:linear-gradient(0deg,rgba(0,0,0,.015),transparent)}
.foot b{color:var(--ink)}
"""


def _verdict(passed: bool) -> str:
    return "PASS" if passed else "FAIL"


def _row_html(row: Row, *, with_definition: bool) -> str:
    """One four-slot row. Inputs get a single ``=``; formulas get two."""
    assert_plain_mathml(row.symbol_mathml)
    if row.definition_mathml:
        assert_plain_mathml(row.definition_mathml)
    definition = row.definition_mathml if with_definition else ""
    second_eq = '<span class="eq">=</span>' if with_definition else "<span></span>"
    unit = f'&nbsp;<span class="unit">{escape(row.unit)}</span>' if row.unit else ""
    reference = (
        f'<span class="ref">{escape(row.ref)}</span>' if row.ref else "<span></span>"
    )
    return (
        f'<span class="sym">{row.symbol_mathml}</span>'
        f'<span class="eq">=</span>'
        f'<span class="def">{definition}</span>'
        f"{second_eq}"
        f'<span class="val">{escape(row.value_text)}{unit}</span>'
        f"{reference}"
    )


def _section_html(label: str, rows: tuple[Row, ...], *, with_definition: bool) -> str:
    body = "\n        ".join(
        _row_html(row, with_definition=with_definition) for row in rows
    )
    return (
        '    <div class="sec">\n'
        f'      <p class="sec__label">{escape(label)}</p>\n'
        '      <div class="rows">\n'
        f"        {body}\n"
        "      </div>\n"
        "    </div>"
    )


def _check_html(check: CheckResult) -> str:
    assert_plain_mathml(check.expr_mathml)
    verdict = _verdict(check.passed).lower()
    description = (
        f'<span class="chk__what">{escape(check.description)}</span>'
        if check.description
        else ""
    )
    return (
        '        <div class="chk">\n'
        f'          <div><span class="chk__eq">{check.expr_mathml}</span>'
        f"{description}</div>\n"
        f'          <span class="chk__bool">{escape(check.substituted)}</span>\n'
        f'          <span class="badge badge--{verdict}">{_verdict(check.passed)}</span>\n'
        "        </div>"
    )


def _checks_html(checks: tuple[CheckResult, ...]) -> str:
    body = "\n".join(_check_html(check) for check in checks)
    return (
        '    <div class="sec">\n'
        '      <p class="sec__label">Design checks</p>\n'
        '      <div class="checks">\n'
        f"{body}\n"
        "      </div>\n"
        "    </div>"
    )


def render_html(result: Result) -> str:
    """Render ``result`` as a complete, self-contained HTML document.

    Deterministic by construction: everything drawn here comes from the one
    :class:`~calcsheet.evaluate.Result`, so the same calc renders byte-identical
    output every time.
    """
    verdict = _verdict(result.passed)
    sections = []
    if result.inputs:
        sections.append(_section_html("Inputs", result.inputs, with_definition=False))
    if result.formulas:
        sections.append(
            _section_html("Calculation", result.formulas, with_definition=True)
        )
    if result.checks:
        sections.append(_checks_html(result.checks))
    body = "\n\n".join(sections)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(result.title)} — {escape(result.as_of)}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <div class="card__head">
      <h1 class="card__title">{escape(result.title)}</h1>
      <span class="card__asof">AS_OF {escape(result.as_of)}</span>
      <span class="status status--{verdict.lower()}">&#9679; {verdict}</span>
    </div>

{body}

    <div class="foot">
      Overall <b>{verdict}</b> — a calc is valid only when <b>every</b> check passes.
    </div>
  </div>
</div>
</body>
</html>
"""
