# UI Review 0005 — Integrated graph-engine app (wave-1)

Adversarial hands-on review of the fully integrated app at
`integration/wave-1` (`e9c03d46`), driven with Playwright/Chromium against
`python -m server --demo --no-open` (12-node showcase graph, built `web/dist`).
Review only — nothing was fixed. All file references are relative to
`graph-engine/`.

Method: scripted browser sessions exercising the canvas, per-node inspection,
runs, source editing, and every widget kind; deliberate abuse (stale-snapshot
races, invalid expressions, unknown columns, simulated 422/aborted requests,
long values, injected unknown node types and foreign recipe values). Screenshots
were saved to the session scratchpad
(`/tmp/claude-0/-home-user-n8n/bb1be04a-e997-58f7-9016-e77b3574a884/scratchpad/review-*.png`);
paths below are the file names in that directory. Every mutation the review made
through the app was reverted; the working tree is clean.

## Prioritized findings

| # | Sev | Area | Issue | Suggested direction | Where |
|---|-----|------|-------|---------------------|-------|
| 1 | High | Widget seam | **Lost update between quick widget commits.** Each commit PUTs a whole-graph snapshot taken at the last reload. Reproduced: slow commit A (title), fast commit B (symbol) → B lands first, then A's stale snapshot overwrites it. B's value is silently reverted, no error anywhere. | Serialize commits through one queue that re-diffs against the latest served graph, or send per-field patches, or add optimistic-concurrency (version/ETag) to `PUT /api/graph`. | `web/src/widgets/context.tsx:30-48`, `web/src/App.tsx:84-87` |
| 2 | High | Widget seam | **Click-outside never closes an open editor.** The documented primary dismissal (document `mousedown` listener) never fires for canvas clicks — ReactFlow's pane (d3-zoom) stops `mousedown` propagation before it reaches the document. Clicking another node's chip doesn't close it either, so multiple editors stack open; the only working dismissal is the small "Done" button. | Register the listener in the capture phase (`addEventListener('mousedown', fn, true)`), or use `pointerdown` capture. | `web/src/widgets/WidgetSlot.tsx:63-72`; screenshot `review-14-long-title-chip.png` |
| 3 | High | Source bijection | **First widget commit persists the demo's machine-absolute CSV path into `showcase.py`.** The demo rewrites `read_table.path` to an absolute path in the *served* graph; the first widget commit writes that whole graph back, so the source file gains `path='/home/user/n8n/.claude/worktrees/…/showcase.csv'`. Any first edit dirties the file with a non-portable path. | Apply the path override at run time only (keep the served/persisted graph pristine), or write back only literals that actually changed. | `server/demo.py:34-39` + `server/workspace.py` write-back |
| 4 | High | Math widget | **The sympy→LaTeX mini-translator renders wrong math confidently.** `x**(y+1)` → "x⋅⋅(y+1)", `2**x**2` → "2^x⋅⋅2", `sqrt(sqrt(x))` → a mangled nested radical. All are valid SymPy that KaTeX happily renders — no fallback triggers, so the preview asserts an incorrect reading of a correct expression. (The monospace fallback does fire for KaTeX-invalid output like `a & b`.) | Detect the unsupported shapes (`**(`, nested calls) and fall back to monospace; or label the preview "approximate"; or do the translation in Python where SymPy's real `latex()` lives. | `web/src/widgets/math/MathEditor.tsx:38-107`; `review-11-math-fallback.png` |
| 5 | High | Source bijection | **A one-literal edit rewrites the whole `@main` body, deleting comments and formatting.** One title commit collapsed 34 hand-written lines (comments, multi-line recipe dict) into 12 generated lines. The projection is by design (ADR 0004), but silently destroying a user's comments on the first chip edit is real data loss for a tool whose promise is "the graph edits your source". | At minimum warn once before the first rewrite of a file with comments; longer-term, preserve comments/formatting via CST-based editing (e.g. libcst) or restrict rewrites to the changed statement. | observed via `git diff` after any commit; `server/workspace.py` |
| 6 | Med | Run inspection | **A failed run discards all upstream values.** With `pick.index = 999`, the run fails at `first` and `run.outputs` comes back empty: the per-node panel shows nothing and the inspector shows "no value yet" for every node that *did* execute — exactly when you need the values to debug. | Return partial outputs for successfully executed nodes alongside the error. | server `/api/run`; `web/src/components/RunResultsPanel.tsx:76-90`; `review-15-run-error.png` |
| 7 | Med | Canvas layout | **Fit zoom is unreadable; layout is wide with unused vertical space (confirmed).** The 12-node showcase lays out 8 layers (~2680×708 flow px, 3.8:1) in a 1.7:1 viewport, so fitView settles at 47% zoom: docstrings and socket labels are illegible, and editors open at that scale (math input renders 88×13 px; the 680px recipe editor renders 318×175). ~250px bands above/below the graph are empty. | Compact the layout (source nodes like `latex_to_mathml` sit at layer 0 despite feeding layer 6 — assign layers by longest path *to sink* or wrap parallel chains), and/or zoom to the node when an editor opens. | `web/src/layout.ts:73-123`; `review-01-initial-canvas.png`, `review-10-math-editor-open.png`, `review-17-recipe-editor.png` |
| 8 | Med | Widget seam | **Chip click also selects the node and opens the inspector (confirmed).** One click produces two overlapping reactions: the editor expands in place while the inspector slides over the right third of the canvas (covering downstream nodes). | `stopPropagation` on chip click; open the inspector only from header/body clicks. | `web/src/GraphView.tsx:176-178`, `web/src/widgets/WidgetSlot.tsx:83-95`; `review-13-long-title-editing.png` |
| 9 | Med | Run inspection | **Results panel lists nodes by graph id only (confirmed).** The panel says `raw`, `sales`, `table_card`; the cards say `read_table`, `apply_recipe`, `table_summary` — and the cards never display their graph id, so there is no visible shared key between the two surfaces. | Render "id · spec title" in the panel and make rows click-to-focus the node. | `web/src/components/RunResultsPanel.tsx:76-78`; `review-04-run-results.png` |
| 10 | Med | Math widget | **Stale preview race on first open.** Typing immediately after opening the editor can leave the *previous* value's KaTeX render displayed under the new draft (deterministically reproduced: draft `x ] y & z` showed `x²−5·x+6`). The preview effect has no sequence guard, unlike the table preview's `previewSeq`. | Track a seq/AbortController per draft like `table/TableRecipeEditor.tsx:299`. | `web/src/widgets/math/MathEditor.tsx:166-179`; `review-33-math-fallback-dark.png` |
| 11 | Med | Widgets | **Int-subtype number editor accepts and persists floats.** `pick.index` declares `subtype: int` but `2.5` commits and round-trips into the source; Python only objects at the next run. | Reject/round non-integers when `subtype === 'int'` before committing. | `web/src/widgets/builtins.tsx:44-59` |
| 12 | Med | Keyboard/a11y | **Escape closes nothing** — not the widget editor, the inspector, or the results/export panels. Chips are real buttons (Enter opens them — good), but with click-outside also broken (#2) a keyboard user's only exit is tabbing to "Done". | Add an Escape handler at the slot/panel level. | `web/src/widgets/WidgetSlot.tsx`, `web/src/GraphView.tsx` |
| 13 | Med | Table widget | **Every preview keystroke re-runs the whole graph.** One short editing session fired 13 `POST /api/run` full-graph executions (including the SymPy chain). Fine at demo scale; a real graph with a slow node makes the grid preview sluggish and the server busy. | Run only the anchor's upstream subgraph for previews, or cache upstream results server-side. | `web/src/widgets/table/preview.ts:95-143` |
| 14 | Low | Table widget | Preview errors keep the server's `node 'sales' (table.apply_recipe) raised UserError:` prefix even though the editor code strips node-id prefixes — the prefix is baked into the message string, so the "reads as this editor's own error" intent fails. | Have the server return structured `{nodeId, rawMessage}` or strip the known prefix pattern. | `web/src/widgets/table/TableRecipeEditor.tsx:316-320`; `review-19-recipe-bad-expr.png` |
| 15 | Low | Node cards | Docstring clamp shows a half-cut third line of text below the 2-line clamp (visible on `describe`/`table_summary` cards) — `-webkit-line-clamp: 2` and the box height disagree. | Align max-height with the clamp or add `overflow: hidden` on the right element. | `web/src/styles.css:361`; `review-02-node-closeup.png` |
| 16 | Low | Node cards | Post-run result chips dump raw JSON/HTML (`<div style="font-family:…`) into the card footer. Truncated safely, but noisy; a type-aware summary ("table 3×4", "html · 1.2 KB") would read better. | Summarize by `previewType` in the chip, full value in the inspector. | `web/src/components/SpecNode.tsx:10-27`; `review-07-canvas-with-chips.png` |
| 17 | Low | Math widget | Fallback/preview styling hardcodes light-theme colors (`#f5f5f5` bg, `#666` text) and inline styles in an otherwise dark, stylesheet-driven UI. | Move to `styles.css` tokens. | `web/src/widgets/math/MathEditor.tsx:123,201-216` |
| 18 | Low | Inspection | The inspector's type column silently switches from declared type to run-time type after a run (`object` → `Add`); informative, but there's no cue that the label changed meaning. | Show both ("object · Add at run"). | `web/src/components/NodeInspector.tsx:56-58` |
| 19 | Low | Widgets | For inputs with no literal, the chip shows the widget *kind* ("number", "text") in the same style used for values elsewhere — "precision  number" reads like a value. | Style kind-chips differently (e.g. dashed border / "edit…"). | `web/src/widgets/WidgetSlot.tsx:81` |
| 20 | Low | Toolbar | The Controls fit-view button uses ReactFlow's default padding, not the app's `padding 0.15 / maxZoom 1.05`, so the two fits frame slightly differently. | Pass matching `fitViewOptions`. | `web/src/GraphView.tsx:135,210` |

## What was verified and works well

- **Trust boundaries are right.** The run output renders in a fully sandboxed
  iframe (`sandbox=""`, `srcDoc`) — untrusted node HTML can't touch the host
  page. Zero CDN: KaTeX is bundled, the sym card is native MathML
  (`review-04-run-results.png`).
- **The commit seam does not jank.** A widget commit patches node data in
  place: viewport transform, node positions, and measured sizes are preserved
  (verified byte-identical transform before/after); no re-layout, no loading
  flash. The measure→layout→frame→reveal pipeline means the user never sees a
  mispositioned graph.
- **Failure honesty.** A rejected `PUT /api/graph` shows a clear banner, the
  chip reverts to server truth (no fake success), and the banner
  self-dismisses (`review-25-commit-failure.png`). Transport failures read
  well: "Could not reach the server at /api/run. Is it running?".
- **The table-recipe editor is the strongest piece.** Python-authoritative
  preview with a sequence guard, last-good-result dimming while a broken draft
  shows its error, per-step column propagation into pickers, and genuinely
  excellent error messages ("unknown name 'bogus' in expression; available
  columns: ['amount', 'qty', 'region']"). Add/reorder/remove/limit all work;
  Result/Input tabs show row×col counts (`review-17`–`review-22`).
- **Degrade paths exist and are labelled.** Unknown node types render a
  "missing spec" card that keeps its edges (`review-23-missing-spec.png`); a
  non-v1 recipe gets an honest "unrecognised" raw-JSON editor with a reset
  (`review-24-foreign-recipe.png`).
- **Source editing round-trips.** Syntax errors are rejected server-side
  without touching the file; a body edit saves, re-introspects, and the next
  run reflects it; a signature-breaking save warns precisely which edge no
  longer binds (`review-26`–`review-30`). The branch badge names the branch and
  its tooltip names the files edits land on.
- **Run errors point at the node**: structured code + node id + message, and
  the failing card gets error styling on canvas (`review-15-run-error.png`).

## Screenshot index

All under
`/tmp/claude-0/-home-user-n8n/bb1be04a-e997-58f7-9016-e77b3574a884/scratchpad/`
(session-local; not committed):

`review-01-initial-canvas.png` (fit-zoom framing), `review-02-node-closeup.png`
(card anatomy + doc clamp), `review-03/06` (inspector pre/post-run),
`review-04/05/07` (run results, refit, result chips),
`review-10/11/12/33` (math editor: open, wrong render, good render, stale
preview), `review-13/14` (chip→inspector overlap; editor stuck open after
outside click), `review-15` (failed run, empty per-node outputs),
`review-17/18/19/20/21/22` (recipe editor flows), `review-23/24` (missing spec,
foreign recipe), `review-25` (commit rejection banner), `review-26`–`review-30`
(source editor flows), `review-31` (export), `review-32` (run transport error).

## Summary

The integrated app delivers its core promise: a live canvas whose literals,
recipes, and even node bodies genuinely round-trip to a real Python file on a
real branch, with Python staying the single authority for every computation and
untrusted output kept sandboxed. The table-recipe editor and the
source-editing loop are the standouts; error surfacing is mostly honest and
specific.

The gaps cluster at the *editing seam under pressure*: two quick commits can
silently lose one (1), the primary dismissal gesture doesn't work (2), and the
first commit both dirties the source with a machine path (3) and strips the
file's comments (5). The math preview is the one surface that actively
misleads (4, 10). And at the default fit zoom the whole editing story is
physically too small to use (7) — the demo's first impression is a beautiful
but illegible ribbon. None of these are architectural; all are fixable within
the current seams, and 1–4 are the ones I'd hold the release for.
