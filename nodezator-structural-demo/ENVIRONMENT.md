# Environment requirements & cloud-env handoff

What the roadmap needs from the execution environment — staged by phase, so you
can provision incrementally. **Verified against the current session** where noted.

## Bottom line

- **No LLM API key is required.** The agent phase (former Phase 7) was dropped,
  so the roadmap needs **zero external secrets**.
- **Phases 0–2 (core, Nodezator nodes, symbolic): need nothing new.** Only PyPI,
  which is already reachable. We can start immediately.
- **Phases 4–6 (web/VS Code UI): need the npm registry** — already reachable.
- **CDNs are blocked**, so all web assets (ReactFlow, KaTeX/MathJax, MathLive)
  are **bundled locally via npm**, never loaded from a CDN at runtime.

## Already provisioned in the current session (verified)

| Tool / value | Status |
|---|---|
| node 22 / npm 10 / pnpm 10 | ✅ present |
| uv 0.8, git, Python 3.11 | ✅ present |
| Chromium (`/opt/pw-browsers`, `PLAYWRIGHT_BROWSERS_PATH` set) | ✅ present |
| `pypi.org`, `files.pythonhosted.org` | ✅ 200 |
| `registry.npmjs.org` | ✅ 200 |
| `cdn.jsdelivr.net` / public CDNs | ❌ blocked → bundle locally |
| LLM API key | ➖ not required (agent phase dropped) |

## Full requirements by phase

| Phase | Secrets | Env vars | Network (allow) |
|---|---|---|---|
| 0 Core | — | — | pypi.org, files.pythonhosted.org |
| 1 Nodes/inputs | — | — | (same) |
| 2 Symbolic | — | — | (same; `sympy` from PyPI) |
| 3 Table + UI decision | — | — | (same) |
| 4 Web shell | — | `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`, `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1` | + registry.npmjs.org |
| 5 Rich widgets | — | (same) | (same; assets bundled, no CDN) |
| 6 VCS in UI | — | (same) | + open-vsx.org **or** marketplace.visualstudio.com, update.code.visualstudio.com *(only if hosting real VS Code)* |

The roadmap ends at Phase 6 and requires **no secrets**.

Notes:
- **RFEM stays mocked** — no external host or credentials. Only if we later wire
  the *real* Dlubal API do we need its endpoint (LAN gRPC in RFEM 6 / SOAP in
  RFEM 5) + license — out of scope for this roadmap.
- **No LLM API keys** (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY`) — the agent phase
  was dropped. If an embedded Copilot is revisited later, that's when a key
  (and `api.anthropic.com` on the allowlist) would be added.

## Recommended network policy

A **custom allowlist** is ideal. Minimum set for the whole roadmap:

```
pypi.org
files.pythonhosted.org
registry.npmjs.org
# only if Phase 6 hosts real VS Code / installs extensions:
open-vsx.org
marketplace.visualstudio.com
update.code.visualstudio.com
```

If a custom allowlist isn't practical, pick the preset that permits PyPI + npm
outbound. We deliberately **do not** depend on CDNs, so the policy does not need
to open `*.jsdelivr.net` / `unpkg.com`. No LLM endpoint is needed.

## Creating the cloud environment (Claude Code on the web)

See https://code.claude.com/docs/en/claude-code-on-the-web for the current UI.
When creating/editing the environment:

1. **Repository / branch:** point at this repo; work branch
   `claude/nodezator-gui-python-conversion-nm1tgv`.
2. **Network policy:** apply the allowlist above (or the closest preset).
3. **Environment variables:** no secrets required. For the web phases set —
   - `PLAYWRIGHT_BROWSERS_PATH` = `/opt/pw-browsers`
   - `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD` = `1`
4. **Setup script (optional but handy):** see below — pre-installs deps so the
   first session is ready to run.

### Suggested setup script

```bash
#!/usr/bin/env bash
set -euo pipefail
cd nodezator-structural-demo
uv sync --extra export        # core + Markdown/PDF export deps
# Web phases (uncomment from Phase 4 on):
# corepack enable && pnpm --dir web install
```

## Handoff prompt for a new cloud env

Paste this as the first message in the new environment to resume with full
context:

> We are building a graph-based Python calculation IDE, starting from the
> Nodezator demo in `nodezator-structural-demo/`. Read `ROADMAP.md` and
> `ENVIRONMENT.md` in that folder first — they define the feature set, how each
> maps to Nodezator's graph model, the phased plan, and the environment
> requirements. Work on branch `claude/nodezator-gui-python-conversion-nm1tgv`.
> Confirm the toolchain (`uv`, `node`, Chromium at `/opt/pw-browsers`) and PyPI
> reachability, then start at **Phase 0 (headless engine core)**: extract a
> UI-agnostic package exposing `node_spec(fn)`, a `Graph` model, `run(graph)`,
> and `to_python(graph)`, and freeze the node-spec + graph JSON schema. Stop at
> the Phase 0 checkpoint and show me the schemas + the four entry points before
> proceeding. No LLM API key is needed (the agent phase was dropped). Do not
> load assets from CDNs — bundle locally (they're blocked).
