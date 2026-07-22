"""Export the calculation to Markdown and PDF — and back again.

Forward:
    python export_report.py 0          # -> report.md  and  report.pdf

Reverse (the honest round-trip):
    python export_report.py --extract report.pdf

The calculation "object" is just a LaTeX string plus the scalar inputs. That is
trivial to render *forward* into Markdown or PDF. Going *backward* from a PDF is
only faithful if the source travelled inside the file — so the PDF we write
carries the inputs + LaTeX as an embedded attachment. "Convert back" then means
*extract the payload*, not *reverse-engineer the pixels*.

Markdown needs no third-party libs. PDF uses the pre-installed Chromium (via
Playwright) to print the MathJax page, then pypdf to embed the source.
"""

import base64
import glob
import json
import os
import sys
from pathlib import Path

from demolib import read_members_csv, select_member, unpack_member, render_stress_check

HERE = Path(__file__).resolve().parent
CSV_PATH = HERE / "members.csv"
MD_OUT = HERE / "report.md"
HTML_TMP = HERE / "report.html"
PDF_OUT = HERE / "report.pdf"

# Name of the embedded-source attachment inside the PDF.
SOURCE_ATTACHMENT = "calc_source.json"


def _gather(index: int) -> dict:
    """Run the pipeline and collect inputs + rendered calc into one payload."""
    member = select_member(read_members_csv(str(CSV_PATH)), index=index)
    f = unpack_member(member)
    calc = render_stress_check(f["force_kN"], f["width_mm"], f["thickness_mm"], f["fy_MPa"])
    return {
        "schema": "nodezator-structural-demo/calc@1",
        "index": index,
        "inputs": {k: f[k] for k in ("name", "force_kN", "width_mm", "thickness_mm", "fy_MPa")},
        "utilisation": calc["utilisation"],
        "latex": calc["latex"],
        "summary": calc["summary"],
    }


# --------------------------------------------------------------------------- #
# Forward: Markdown
# --------------------------------------------------------------------------- #
def to_markdown(payload: dict) -> Path:
    """Write a Markdown file. GitHub/Jupyter/VS Code render the $$...$$ math."""
    latex = payload["latex"].strip()
    body = latex[2:-2].strip() if latex.startswith("$$") and latex.endswith("$$") else latex
    i = payload["inputs"]
    status = "PASS ✅" if payload["utilisation"] < 1.0 else "FAIL ❌"

    md = f"""# Axial stress check — {i['name']}

| Input | Value |
|---|---|
| Force `P` | {i['force_kN']} kN |
| Section | {i['width_mm']} × {i['thickness_mm']} mm |
| Yield `f_y` | {i['fy_MPa']} MPa |

**Acceptance criterion:** `f(x) = utilisation < 1` → **{status}** \
(utilisation = {payload['utilisation']:.3f})

$$
{body}
$$

<!-- calc-source (do not edit): {base64.b64encode(json.dumps(payload).encode()).decode()} -->
"""
    MD_OUT.write_text(md, encoding="utf-8")
    return MD_OUT


# --------------------------------------------------------------------------- #
# Forward: PDF (Chromium print-to-PDF + embedded source)
# --------------------------------------------------------------------------- #
def _html(payload: dict) -> str:
    latex = payload["latex"].strip()
    body = latex[2:-2].strip() if latex.startswith("$$") and latex.endswith("$$") else latex
    i = payload["inputs"]
    status = "PASS" if payload["utilisation"] < 1.0 else "FAIL"
    colour = "#1a7f37" if status == "PASS" else "#cf222e"
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Stress check — {i['name']}</title>
<script>window.MathJax={{startup:{{pageReady(){{return MathJax.startup.defaultPageReady().then(()=>{{window.__typeset_done=true;}});}}}},tex:{{displayMath:[['\\\\[','\\\\]']]}}}};</script>
<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
<style>body{{font-family:system-ui,sans-serif;margin:2.5cm;}}
.status{{font-weight:700;color:{colour};}} table{{border-collapse:collapse;}}
td,th{{border:1px solid #ccc;padding:4px 10px;text-align:left;}}</style></head>
<body>
<h1>Axial stress check — {i['name']}</h1>
<table><tr><th>Force P</th><td>{i['force_kN']} kN</td></tr>
<tr><th>Section</th><td>{i['width_mm']} × {i['thickness_mm']} mm</td></tr>
<tr><th>Yield f_y</th><td>{i['fy_MPa']} MPa</td></tr></table>
<p>Acceptance: <code>f(x) = utilisation &lt; 1</code> →
<span class="status">{status}</span> (utilisation = {payload['utilisation']:.3f})</p>
<div>\\[{body}\\]</div>
</body></html>"""


def _chromium_executable() -> str:
    for pat in ("chromium-*/chrome-linux/chrome", "chromium_headless_shell-*/chrome-linux/headless_shell"):
        hits = glob.glob(str(Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")) / pat))
        if hits:
            return hits[0]
    raise RuntimeError("no pre-installed Chromium found under PLAYWRIGHT_BROWSERS_PATH")


def to_pdf(payload: dict) -> Path:
    from playwright.sync_api import sync_playwright  # local import: only needed for PDF

    HTML_TMP.write_text(_html(payload), encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=_chromium_executable(), args=["--no-sandbox"])
        page = browser.new_page()
        page.goto(HTML_TMP.as_uri())
        try:
            page.wait_for_function("window.__typeset_done === true", timeout=15000)
        except Exception:
            pass  # no network for MathJax -> PDF still shows the raw LaTeX, readably
        page.pdf(path=str(PDF_OUT), format="A4", print_background=True)
        browser.close()

    _embed_source(PDF_OUT, payload)
    return PDF_OUT


def _embed_source(pdf_path: Path, payload: dict) -> None:
    """Attach the source JSON inside the PDF + stamp metadata, enabling round-trip."""
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(pdf_path))
    writer = PdfWriter()
    writer.append(reader)
    writer.add_attachment(SOURCE_ATTACHMENT, json.dumps(payload, indent=2).encode("utf-8"))
    writer.add_metadata({
        "/Title": f"Axial stress check — {payload['inputs']['name']}",
        "/Subject": "nodezator-structural-demo calc; source embedded as attachment",
        "/Keywords": "utilisation=%.4f" % payload["utilisation"],
    })
    with pdf_path.open("wb") as fh:
        writer.write(fh)


# --------------------------------------------------------------------------- #
# Reverse: PDF -> source payload
# --------------------------------------------------------------------------- #
def extract(pdf_path: str) -> dict:
    """Recover the original inputs + LaTeX from the PDF's embedded attachment."""
    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    attachments = reader.attachments  # {name: [bytes, ...]}
    if SOURCE_ATTACHMENT not in attachments:
        raise SystemExit(
            f"No embedded source in {pdf_path}. A PDF printed without the source "
            f"attachment cannot be faithfully reversed — see README."
        )
    payload = json.loads(bytes(attachments[SOURCE_ATTACHMENT][0]).decode("utf-8"))

    # Prove the recovered inputs reproduce the calc exactly.
    i = payload["inputs"]
    reproduced = render_stress_check(i["force_kN"], i["width_mm"], i["thickness_mm"], i["fy_MPa"])
    match = abs(reproduced["utilisation"] - payload["utilisation"]) < 1e-9
    print(f"Recovered member : {i['name']}  (row index {payload['index']})")
    print(f"Recovered inputs : {i}")
    print(f"Embedded util.   : {payload['utilisation']}")
    print(f"Re-computed util. : {reproduced['utilisation']}  -> {'MATCH' if match else 'MISMATCH'}")
    return payload


def main(argv: list) -> int:
    if argv and argv[0] == "--extract":
        extract(argv[1])
        return 0
    index = int(argv[0]) if argv else 0
    payload = _gather(index)
    md = to_markdown(payload)
    print(f"Markdown -> {md}")
    try:
        pdf = to_pdf(payload)
        print(f"PDF      -> {pdf}  (source embedded as '{SOURCE_ATTACHMENT}')")
    except Exception as exc:
        print(f"PDF step skipped ({type(exc).__name__}: {exc}); Markdown still written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
