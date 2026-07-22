{
  description = "graph-engine dev shell — reproducible Python + Node + Playwright toolchain";

  # --- Pinned toolchain source ---------------------------------------------
  # nixpkgs is pinned to the `nixos-unstable` channel branch. On the first
  # `nix develop` (or `nix flake lock`) Nix resolves this branch to an EXACT
  # commit + narHash and records it in flake.lock, which is what makes the
  # environment reproducible from then on. We deliberately track a channel ref
  # rather than hard-coding a bare commit SHA in this file: this repo was
  # authored in a build environment WITHOUT nix, so a specific SHA could not be
  # fetched/verified here, and an unverifiable SHA would hard-fail on lock. See
  # docs/NIX.md for how to pin to an exact rev and how to update the lock.
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    # To pin to an exact revision instead (fully reproducible, no lock needed),
    # replace the line above with e.g.:
    #   nixpkgs.url = "github:NixOS/nixpkgs/<40-char-commit-sha>";
  };

  outputs =
    { self, nixpkgs }:
    let
      # Target platforms. Linux x86_64 is the measured environment; the others
      # are supported best-effort (the toolchain attributes exist on all four).
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f system);
    in
    {
      devShells = forAllSystems (
        system:
        let
          pkgs = import nixpkgs { inherit system; };

          python = pkgs.python311;

          # Playwright browsers built by nixpkgs. Set as PLAYWRIGHT_BROWSERS_PATH
          # so @playwright/test resolves Chromium from the nix store instead of
          # downloading it. NOTE: the browser *build number* this driver ships
          # tracks the nixpkgs `playwright` version, which may differ from the
          # project's @playwright/test@1.61.1 (Chromium build chromium-1194 /
          # 141.0.7390.37). If they diverge, use the `chromium` fallback below —
          # see the "Playwright / Chromium" section of docs/NIX.md.
          playwrightBrowsers = pkgs.playwright-driver.browsers;

          isLinux = pkgs.stdenv.isLinux;
        in
        {
          default = pkgs.mkShell {
            packages =
              [
                python
                pkgs.uv # Python packaging / runner used by the project
                pkgs.nodejs_22 # Node 22.x LTS
                pkgs.pnpm_10 # pnpm 10.x (matches the web/ lockfile)
                pkgs.git
                # A C toolchain — most Python deps here are pure-Python
                # (sympy / handcalcs / forallpeople / latex2mathml / fastapi /
                # uvicorn), but this keeps `uv` able to build a wheel from
                # source if a transitive ever needs it.
                pkgs.gcc
                pkgs.gnumake
                pkgs.pkg-config
                # A standalone Chromium as a reliable fallback for Playwright
                # when the driver's browser build doesn't match 1.61.1.
                pkgs.chromium
              ]
              # Playwright's bundled browsers only run on Linux; on Darwin the
              # system WebKit/Chromium is used and this derivation isn't built.
              ++ pkgs.lib.optional isLinux playwrightBrowsers;

            shellHook = ''
              # --- uv: use the nix Python, never a downloaded one -------------
              export UV_PYTHON="${python}/bin/python3.11"
              export UV_PYTHON_DOWNLOADS=never

              # --- Playwright: use nix-provided browsers, skip the download ---
              export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
              ${pkgs.lib.optionalString isLinux ''
                export PLAYWRIGHT_BROWSERS_PATH="${playwrightBrowsers}"
              ''}
              # Reliable Chromium binary from the nix store. The web/
              # playwright config prefers /opt/pw-browsers (absent under nix);
              # point its executablePath at this if the driver build mismatches.
              export PLAYWRIGHT_CHROMIUM_BIN="${pkgs.chromium}/bin/chromium"

              echo "──────────────────────────────────────────────────────────"
              echo " graph-engine dev shell"
              echo "   python : $("${python}/bin/python3.11" --version 2>&1)"
              echo "   uv     : $(uv --version 2>&1)"
              echo "   node   : $(node --version 2>&1)"
              echo "   pnpm   : $(pnpm --version 2>&1)"
              echo ""
              echo " Python:"
              echo "   uv sync --extra dev --extra sym --extra server"
              echo "   uv run --extra dev --extra sym --extra server python -m pytest -q"
              echo "   uv run --extra server python -m server --demo   # http://127.0.0.1:8000/"
              echo " Web (from graph-engine/web):"
              echo "   pnpm install && pnpm build && pnpm typecheck"
              echo "   pnpm test        # Playwright (nix Chromium)"
              echo "──────────────────────────────────────────────────────────"
            '';
          };
        }
      );
    };
}
