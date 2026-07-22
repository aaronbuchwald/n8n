# Feature roadmap: from Nodezator demo to a rich graph IDE

This document (1) maps every requested feature to **how Nodezator builds the
graph** and how much is native vs. custom, and (2) proposes a **de-risked,
checkpointed implementation order** we work through interactively.

## TL;DR — the one insight that shapes the whole plan

Nodezator cleanly splits into two things:

- **A reusable Python core** — introspect functions → node specs, a graph data
  model, a topological executor, and a graph→Python emitter. This is
  UI-agnostic and is the valuable part.
- **A replaceable UI** — today a self-rendered **pygame** desktop app.

Your nine features fall on two sides of a line:

| Features | Nature | Home |
|---|---|---|
| 1–5 (graph↔Python, pure-Python nodes, inputs/APIs, arbitrary code, forallpeople/handcalcs/symbolic) | **logic** | Native to Nodezator's core — buildable *today* |
| 6–8 (embedded spreadsheet, visual equation editor, VCS-from-UI) | **rich UI + platform** | Outgrow pygame — pull toward a **web / VS Code-hosted** editor over the same core |
| 9 (embedded Copilot/agents) | **deferred** | out of scope for this roadmap (no LLM API key needed) | — |

So the strategy is: **prove the reusable core first (cheap, in Nodezator),
then replace the weak pygame UI with a [ReactFlow](https://reactflow.dev/)
front-end over that same core (Phase 4) exactly when a feature forces it — never
before.** The ReactFlow re-render is the backbone that unlocks features 6–8, and
its first checkpoint is a **PR that shows the graph re-rendered in ReactFlow**
beside the pygame original. Every phase leaves a reviewable checkpoint.

---

## How Nodezator builds the graph (the model everything reuses)

Established by reading Nodezator's source (`graphman/pythonrepr.py`,
`appinfo.py`, node-loading + preprocessing):

1. **Node definition = a Python callable.** A node script is a folder with a
   `__main__.py` that binds `main_callable = fn` (plus optional
   `signature_callable`, `substitution_callable`, `call_format`,
   `stlib_import_text`, `third_party_import_text`).
2. **Node spec via introspection.** Nodezator reads `fn`'s signature:
   **parameters → input sockets**, **return annotation → output socket(s)**
   (a list-of-dicts annotation = multiple named outputs), and
   **`(annotation, default)` → the input widget**. The **docstring** becomes the
   node's on-canvas documentation — this is your "annotation describing each
   node."
3. **Graph = data.** A saved graph (`.ndz`) is a serialized data structure of
   node instances (which script, position, current widget values) + connections
   (output-socket → input-socket edges). Unconnected inputs keep their widget
   value; connected inputs take the upstream value.
4. **Execution = lazy topological sweep.** It repeatedly tries to emit/run each
   node; a node whose parent isn't ready raises `WaitingParentException` and is
   retried next pass — parents therefore always resolve before children.
5. **Export = graph→Python.** `python_repr()` names each output
   `_<socket-id>`, turns each connection into "pass that variable as this
   argument", turns each widget value into a `repr()` literal, and emits one
   `_out = node_title(args…)` line per node — a flat script that **calls your
   original functions**. That is the "converts directly back to the original
   Python" guarantee.

Keep this model in mind: **spec (from introspection) → graph (data) →
execute/export (deterministic passes).** Our Phase 0 extracts exactly this as a
headless engine so any UI can drive it.

---

## Feature support matrix

| # | Feature | Nodezator support | How it lands in the graph | What we build |
|---|---|---|---|---|
| 1 | Graph UI + per-node annotation, converts back to Python | **Native** | docstring = annotation; `python_repr()` = back-to-Python | Nothing new; validate round-trip |
| 2 | Define nodes via pure Python + define the whole graph | **Native (nodes); partial (graph-as-code)** | node = `main_callable`; graph = `.ndz` data | A small **graph-as-Python/JSON** authoring helper |
| 3 | Input types: CSV, RFEM API (mock) | **Native** | each source = a node returning data | CSV node (have it) + **RFEM mock client** node |
| 4 | Arbitrary code nodes returning a value | **Native** | any callable, incl. imperative | Example nodes (have `capacity_margin`) |
| 5 | Sequence → calcs via forallpeople + handcalcs + symbolic engine | **Native (forallpeople/handcalcs); add SymPy** | each step = a node; values flow on edges | **SymPy nodes** + numeric/symbolic cross-check |
| 6 | Embedded CSV/Excel-like table in the graph | **Custom viewer node (pygame) — limited** | a viewer/widget node holding a grid | Web **data-grid node** (pivot trigger) |
| 7 | Symbolic equation editing in the editor → Python | **Gap** (no native math editor) | a node whose widget *is* an equation editor | Web **MathLive/MathQuill → SymPy** node |
| 8 | Version control from the UI (VS Code / Code-OSS lineage) | **Gap** (standalone app, no VCS) | graph files + generated `.py` are diffable | VS Code-hosted editor + **graph-aware diff** |
| 9 | Embedded Copilot with arbitrary agents | **Deferred — out of scope** | — | Dropped from this roadmap: too far out, and avoids any LLM API-key dependency. Revisit later; the engine API would be the agent's tool surface. |

**Reading the matrix:** 1–5 need *code*, not *platform* — cheap and native.
6 is where a pygame grid stops being worth it. 7–8 need a modern web/editor host.
That boundary is the pivot the roadmap is built around. (9 is deferred — see below.)

---

## Per-feature notes

- **(1) Annotations → Python.** Already true. The docstring shows on the node;
  export reproduces the calling program. We just add a test that round-trips a
  graph → `.py` → run and asserts equality.
- **(2) Graph-as-code.** Nodezator authors graphs in the GUI. For programmatic
  definition we add a thin builder (`Graph().add(fn).connect(a.out, b.in)`) that
  emits both the runnable Python and a Nodezator-compatible `.ndz`, so a graph
  can be defined *either* in the UI or in code.
- **(3) RFEM.** Dlubal RFEM exposes a Python API (SOAP web service in RFEM 5,
  gRPC `dlubal.api` in RFEM 6). We **mock** it with a client that returns the
  same member/section/load data shape as `members.csv`, so the graph is
  identical whether the source is CSV or "RFEM". Swapping the mock for the real
  client later is a one-node change.
- **(4) Arbitrary code.** Any callable, including loops/branches/mutation
  (`capacity_margin` already demonstrates this).
- **(5) Three-layer calcs.** forallpeople = units at the value level; handcalcs
  = typeset presentation at the source level; **SymPy = the math** at the
  expression level (rearrange/solve/differentiate, exact arithmetic). SymPy
  gives "ease of verification": derive `P_max = A·f_y` symbolically and check the
  numeric pipeline against it. Bridge: `sympy.lambdify` → feed forallpeople
  quantities → handcalcs renders.
- **(6) Table node.** Nodezator can host a custom **viewer node**; a full
  editable grid in pygame is possible but costly. On the web it's an off-the-shelf
  data grid (AG Grid / Handsontable) bound to a DataFrame the node owns.
- **(7) Equation editor.** No native math editor. On the web, a
  **MathLive/MathQuill** widget produces LaTeX → parse to a **SymPy** expression
  → emit Python. The node's "widget value" becomes the serialized equation, so
  it still round-trips to code like any other node.
- **(8) VCS from UI.** Graphs and generated code are plain files. Hosting the
  web editor inside **VS Code (Code-OSS — the base Cursor forked)** lets us reuse
  its built-in Git; we add a **graph-aware diff** (semantic node/edge diff, not
  just JSON text diff).
- **(9) Embedded Copilot/agents — deferred, out of scope.** Dropped from this
  roadmap: it's too far out and it's the only thing that would require an LLM API
  key, so removing it keeps the whole plan key-free. If revisited later, the
  natural design is unchanged — the engine's API (list node specs, mutate graph,
  run, export) becomes the agent's tool surface, and "arbitrary agents" = pluggable
  tool/agent definitions. Nothing in Phases 0–6 forecloses it.

---

## Recommended implementation order (with checkpoints)

Each phase is independently valuable and ends at a **review checkpoint** we walk
through before starting the next. Phases 0–2 stay in Nodezator (cheap,
de-risking). Phase 3 forces the UI decision. Phases 4–7 build the web/VS Code
host and layer the rich features on the *same* core.

### Phase 0 — Headless engine core  ·  *checkpoint: the spec/contract*
Extract Nodezator's model into a UI-agnostic package:
`node_spec(fn)` (introspection → JSON schema of inputs/outputs/widgets),
`Graph` (nodes + edges as data), `run(graph)` (topological execute),
`to_python(graph)` (emit runnable script). Freeze the **node-spec + graph JSON
schema** — this is the contract every later UI depends on.
> Review: the JSON schemas and the four engine entry points.

### Phase 1 — Nodes & inputs in Nodezator  ·  *checkpoint: working graph + exported .py*
Build the node pack on the core: CSV reader (have it), **RFEM mock** node,
arbitrary-code node, and the calc chain. Load in Nodezator, wire it, export to
Python, run the export.
> Review: the beam graph runs in Nodezator **and** its exported `.py` reproduces the result.

### Phase 2 — Symbolic layer + verification  ·  *checkpoint: symbolic check passes*
Add SymPy nodes: build the symbolic expression, `solve`/rearrange, `lambdify`
to numbers, and a node that asserts numeric (forallpeople) == symbolic within
tolerance; handcalcs documents both.
> Review: a calc where SymPy independently verifies the numeric utilisation and the derivation renders.

### Phase 3 — Table/grid node + **UI decision**  ·  *checkpoint: go/no-go on the web pivot*
Prototype the embedded table as a Nodezator viewer node to feel the pygame
ceiling, then decide: invest in pygame widgets, or stand up the web shell.
Recommendation: this is the moment to pivot.
> Review: side-by-side of the pygame grid vs. a web data-grid mock; commit to the host.

### Phase 4 — Replace the pygame UI with **[ReactFlow](https://reactflow.dev/)**  ·  *checkpoint: a PR that re-renders the graph*
This is the headline UI upgrade: Nodezator's self-rendered pygame canvas is the
weakest part of the stack, and ReactFlow gives node cards, edges, minimap,
pan/zoom, selection, and theming for free — driven by the Phase-0 engine, not a
rewrite of the logic. Two sub-checkpoints:

- **4a — ReactFlow proof-of-concept PR.** FastAPI exposes the engine's
  `node_spec`/graph/run/export endpoints. A **React + ReactFlow** frontend
  (assets **bundled via npm**, no CDN — CDNs are blocked) reads the *same* beam
  graph and renders it: nodes from `node_spec`, edges from the graph model,
  input widgets from the widget schema. Read-only at first (render + run +
  show exported Python side-by-side with the pygame version).
  > **Deliverable: a PR** titled "Re-render the node graph with ReactFlow",
  > showing the identical graph in ReactFlow next to the pygame screenshot, and
  > exporting identical Python. This is the artifact that demonstrates the
  > upgrade.
- **4b — Interactive parity.** Add drag-to-connect, widget editing, add/delete
  nodes, and persistence back to the graph JSON. Host inside a **VS Code webview
  extension** (Code-OSS — the base Cursor forked) to set up Phases 6–8.
  > Review: build the beam graph *from scratch* in ReactFlow and export **identical** Python.

*(Vue Flow — ReactFlow's Vue sibling, which n8n itself ships — is the fallback
if we later want to align with n8n's frontend; ReactFlow is the primary per the
requirement.)*

### Phase 5 — Rich node UIs: table + equation editor  ·  *checkpoint: round-trip from rich widgets*
Now cheap on the web: the **data-grid node** (feature 6) and the
**MathLive → SymPy equation-editor node** (feature 7), both serializing their
widget state so they still export to Python.
> Review: edit an equation visually → see generated SymPy/Python → it runs in the graph.

### Phase 6 — Version control in the UI  ·  *checkpoint: commit/branch/diff from the editor*
Use VS Code's Git plus a **graph-aware diff** over graph JSON + generated `.py`.
> Review: make a change, view a semantic graph diff, commit and branch from the UI.

### Phase 7 — *(deferred: embedded Copilot + agents)*
Removed from this roadmap to avoid any LLM API-key dependency and because it's
too far out. The engine API built in Phase 0 keeps it a clean future add-on if
we choose to revisit it. **The roadmap now ends at Phase 6.**

---

## The single decision to make now

Everything hinges on one call: **do we build the headless core (Phase 0) first
and treat Nodezator as the throwaway first UI, or race features directly inside
Nodezator and refactor later?** The recommendation is **core-first** — it costs
a little up front and makes the web pivot (Phases 4+) a re-skin instead of a
rewrite. Pick the starting phase and confirm the architecture, and we begin.
