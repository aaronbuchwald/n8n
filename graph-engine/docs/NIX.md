# Reproducing the graph-engine toolchain with Nix

This directory ships a [Nix flake](../flake.nix) that reproduces the
`graph-engine` development toolchain — Python, `uv`, Node, `pnpm`, and a
Chromium for Playwright — pinned to a single `nixpkgs` revision so every machine
gets the same versions. Enter it with `nix develop` and run the exact same
Python / web / Playwright operations this project uses.

## What you get

| Tool | Target version (this env) | Provided by the flake |
|---|---|---|
| Python | 3.11.15 | `python311` (3.11.x) |
| uv | 0.8.17 | `uv` |
| Node | 22.22.2 | `nodejs_22` (22.x LTS) |
| pnpm | 10.3x | `pnpm_10` (10.x) |
| Chromium (Playwright) | 141.0.7390.37 / build `chromium-1194` | `playwright-driver.browsers` + `chromium` — see [caveats](#playwright--chromium) |

Exact patch versions come from the pinned `nixpkgs` (see
[Pinning & the lockfile](#pinning--the-lockfile)). Nix pins the *minor* line for
you (`python311`, `nodejs_22`, `pnpm_10`); the trailing patch is whatever that
`nixpkgs` rev froze.

---

## 1. Install Nix

You need Nix with **flakes** enabled.

### Recommended: Determinate Systems installer (flakes on by default)

```bash
curl --proto '=https' --tlsv1.2 -sSf -L https://install.determinate.systems/nix | sh -s -- install
```

Works on Linux and macOS (and WSL2). Flakes and the new `nix` CLI are enabled
out of the box — nothing else to configure. Restart your shell afterwards.

### Alternative: official installer + manual flakes enable

```bash
sh <(curl -L https://nixos.org/nix/install)          # macOS: default; Linux: add --daemon for multi-user
```

Then enable the experimental features once:

```bash
mkdir -p ~/.config/nix
printf 'experimental-features = nix-command flakes\n' >> ~/.config/nix/nix.conf
```

**macOS vs Linux notes**

- **Linux:** the multi-user daemon install (`--daemon`) is recommended; a
  `/nix` store is created. On SELinux/`/nix`-restricted hosts prefer the
  Determinate installer, which handles this.
- **macOS:** the installer sets up `/nix` via a synthetic volume and adds the
  daemon; on Apple Silicon you get `aarch64-darwin`, on Intel `x86_64-darwin`
  — both are declared in the flake's `systems`.

---

## 2. Enter the environment

```bash
cd graph-engine
nix develop
```

You'll see a banner listing Python/uv/Node/pnpm versions and the key commands.
The first run resolves `nixpkgs` and writes `flake.lock` (see below); later runs
are cached and instant.

### Optional: auto-load with direnv

A [`.envrc`](../.envrc) (`use flake`) is included. With
[direnv](https://direnv.net/) (ideally
[nix-direnv](https://github.com/nix-community/nix-direnv) for caching) installed:

```bash
cd graph-engine
direnv allow          # one-time authorization
```

Now the shell loads automatically whenever you `cd` into `graph-engine/`.

---

## 3. Run the project (from inside the shell)

Every command below is run **from inside `nix develop`** (or a direnv-loaded
shell). They mirror one-to-one how this repo is developed.

### Python — install, test

```bash
cd graph-engine

# Sync all optional dependency groups into a local .venv.
uv sync --extra dev --extra sym --extra server

# Run the full test suite (33 tests).
uv run --extra dev --extra sym --extra server python -m pytest -q

# Run the smallest end-to-end example graph.
uv run python examples/minimal/minimal.py
```

`UV_PYTHON` is set to the nix Python 3.11 and `UV_PYTHON_DOWNLOADS=never`, so
`uv` uses the reproducible nix interpreter and never downloads its own.

The extras come straight from [`pyproject.toml`](../pyproject.toml):
`server` (FastAPI + uvicorn), `sym` (sympy / handcalcs / forallpeople /
latex2mathml), `dev` (pytest / httpx + server deps).

### Web — install, build, typecheck

The `web/` app is its **own** isolated pnpm workspace (not part of the n8n
monorepo). Run its commands from inside `web/`:

```bash
cd graph-engine/web
pnpm install
pnpm build          # tsc project references + Vite production bundle → dist/
pnpm typecheck      # tsc -b --noEmit
```

### Run the app

```bash
cd graph-engine
uv run --extra server python -m server --demo
# → serves specs + sample graph + the built SPA at http://127.0.0.1:8000/
```

Build the web bundle first (`cd web && pnpm build`) so `/` serves the app rather
than a build hint. With the terminal interactive, press **Enter** to open the
view in your browser (`--no-open` disables this).

### Playwright / screenshots

The `web/` e2e boots the FastAPI server **and** the built web app, renders from
the live API, and saves screenshots to `tests/__screenshots__/`
(`graph.png`, `run.png`).

```bash
cd graph-engine/web
pnpm build          # the Playwright config's second webServer also builds+previews
pnpm test           # Playwright: live render + Run/Export, against nix Chromium
```

How the browser is resolved under nix:

- The flake exports `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1` and, on Linux,
  `PLAYWRIGHT_BROWSERS_PATH` pointing at the nix `playwright-driver.browsers`
  store path. **Do not** run `playwright install`.
- The project's [`web/playwright.config.ts`](../web/playwright.config.ts) sets
  `launchOptions.executablePath` to `/opt/pw-browsers/...` **only if that path
  exists**. Under nix it doesn't, so `executablePath` is `undefined` and
  Playwright falls back to resolving Chromium from `PLAYWRIGHT_BROWSERS_PATH` —
  i.e. the nix browser. See the caveats below on version matching.

---

## Playwright / Chromium

This is the one place nix parity is **approximate**, and it's worth
understanding.

`@playwright/test@1.61.1` expects a specific Chromium build — `chromium-1194`
(141.0.7390.37). Playwright finds it by looking for that exact build-numbered
folder inside `PLAYWRIGHT_BROWSERS_PATH`. The nixpkgs `playwright-driver.browsers`
derivation ships the browser build that matches the **nixpkgs** `playwright`
version, which may not be `1.61.1` at the pinned rev — in which case the build
number won't line up and Playwright won't find its browser there.

Check whether they align at your pinned rev:

```bash
# From graph-engine/ (flakes enabled):
nix eval --raw .#devShells.$(nix eval --raw --impure --expr builtins.currentSystem 2>/dev/null || echo x86_64-linux) 2>/dev/null

# Simpler — just read the versions from nixpkgs directly:
nix eval nixpkgs#playwright-driver.version
nix eval nixpkgs#chromium.version
nix eval nixpkgs#nodejs_22.version
nix eval nixpkgs#pnpm_10.version
nix eval nixpkgs#uv.version
nix eval nixpkgs#python311.version
```

**If the driver version is `1.61.x`:** the default path works — `pnpm test`
uses the nix browser via `PLAYWRIGHT_BROWSERS_PATH`. Nothing to do.

**If it differs (likely):** use one of these fallbacks.

1. **Use the standalone nix Chromium (recommended, offline, reproducible).**
   The flake also puts `pkgs.chromium` on `PATH` and exports
   `PLAYWRIGHT_CHROMIUM_BIN`. Point Playwright's `executablePath` at it by
   adding to `web/playwright.config.ts`'s `launchOptions` resolution:

   ```ts
   const executablePath =
     process.env.PLAYWRIGHT_CHROMIUM_BIN ??
     (existsSync(PREINSTALLED_CHROMIUM) ? PREINSTALLED_CHROMIUM : undefined);
   ```

   That is a one-line, backward-compatible change (it still honours
   `/opt/pw-browsers` when present). Chromium 141 vs a nearby nix Chromium is
   fine for these render/screenshot assertions.

2. **Let Playwright fetch its exact browser** (needs network, non-reproducible):

   ```bash
   PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=0 pnpm exec playwright install chromium
   ```

---

## Pinning & the lockfile

- `flake.nix` pins the `nixpkgs` input to the **`nixos-unstable`** channel
  branch. On the first `nix develop` (or `nix flake lock`), Nix resolves that
  branch to an exact commit + content hash and writes **`flake.lock`**. Commit
  that file to freeze the toolchain for everyone.

  ```bash
  cd graph-engine
  nix flake lock          # generate flake.lock (also happens on first `nix develop`)
  git add flake.lock && git commit -m "chore(graph-engine): lock nix toolchain"
  ```

- **Why no `flake.lock` is committed here:** this flake was authored in a build
  environment **without nix installed**, so it was not possible to fetch a
  `nixpkgs` revision or compute the lock's content hash (`narHash`) here. A
  hand-written lock with a fabricated hash would fail verification on first use,
  so we intentionally leave it to be generated on your machine — a single
  reproducible step (`nix flake lock`).

- **To pin to an exact revision** (fully reproducible without relying on the
  branch), edit `flake.nix`:

  ```nix
  nixpkgs.url = "github:NixOS/nixpkgs/<40-char-commit-sha>";
  ```

  then `nix flake lock`. Update later with `nix flake update`.

---

## Parity & caveats

**What the flake reproduces (toolchain + operation parity):**

- Python **3.11**, `uv`, Node **22**, `pnpm 10` — the same tool families and
  minor lines as the measured environment, pinned via `nixpkgs` + `flake.lock`.
- `uv` configured to use the nix Python (`UV_PYTHON`, `UV_PYTHON_DOWNLOADS=never`).
- The exact **operations**: `uv sync` / `pytest`, `pnpm install` / `build` /
  `typecheck`, `python -m server --demo`, and `pnpm test` (Playwright).

**What it deliberately does NOT reproduce:**

- **The cloud egress proxy + CA bundle.** The original build environment routed
  HTTPS through an agent proxy with a custom CA. The flake assumes ordinary
  outbound internet (for `uv sync` and `pnpm install` from public registries);
  it does not install or trust that proxy/CA.
- **The `/opt/pw-browsers` layout.** That fixed path is replaced by the nix
  browser store path (`PLAYWRIGHT_BROWSERS_PATH`) or the standalone nix
  `chromium`. The project's Playwright config already falls back gracefully when
  `/opt/pw-browsers` is absent.
- **Exact patch versions / the Chromium build number.** Nix pins the minor line
  and freezes a patch per rev; the Playwright Chromium build may differ from
  `chromium-1194` (see [Playwright / Chromium](#playwright--chromium)).

The honest summary: this is **toolchain + workflow parity**, not a
byte-identical clone of the original hosted environment. Every command in this
guide runs the same way against the same tool versions; the differences above
are environmental (networking, fixed browser paths) rather than in the code or
its toolchain.
