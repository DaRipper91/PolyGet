# Agent Report

## Summary
Added 12 package-manager drivers (15 → 27) and the plumbing they need. Baseline before changes:
222 tests passing; now 302 passing.

**New drivers** (`app/core/drivers/`): `aur.py` (paru, falling back to yay), `uv.py`, `go.py`,
`bun.py`, `deno.py`, `bundler.py`, `gradle.py`, `snap.py`, `nix.py`, `distrobox.py`, `brew.py`
(one driver for macOS Homebrew and Linuxbrew), `conda.py` (also drives mamba).

**Modified**
- `app/core/manager.py` — added `run_capture()` (query subprocess → `DriverError` on any failure) and
  `fetch_json()` (curl-based). Existing drivers are untouched and keep their own boilerplate.
- `app/core/projects.py` (new) — tracked-project helpers shared by Bundler/Gradle.
- `app/core/settings_store.py` — `projects.dirs` setting + `get/add/remove_project_dir`.
- `app/core/distro.py` — `darwin` → `"macos"` family.
- `app/core/data/manager_catalog.yaml` — `has_driver: true` for aur/go/bundler/gradle/snap/nix/distrobox;
  new entries uv, bun, deno, brew, conda. `paru` entry became `aur` (name must equal driver name —
  enforced by `test_catalog_driver_consistency`); `Go Modules` renamed `Go` for the same reason.
- `app/cli.py` — `projects list|add|remove` command; `outdated`/`upgrade` no longer count
  `NotImplementedError` ("unsupported") as a failure; unbuildable upgrade commands are reported, not raised.
- `app/ui/main_window.py`, `app/ui/tui.py` — same two guards (unsupported scan; unbuildable upgrade command).
- `README.md` — counts, driver table, `projects` command.
- Tests: `tests/conftest.py` (`scripted_exec` fixture) + 9 new test files.

## Feature / Task Status
- ✅ AUR, uv, Go — implemented, tested, and run against the real tools on this machine
- ✅ Bundler, Gradle — implemented, tested, run against real throwaway projects (real `bundle`/`gradle`)
- ✅ Bun — implemented and tested; no global bun packages exist here, so only fixture-verified
- ✅ Deno — list/install/JSR search only; update checks are deliberately unsupported
- 🔄 Snap, Nix, Distrobox, Homebrew, Conda — implemented and unit-tested against fixtures built from
  each tool's documented output format. **None of these binaries is installed on this machine, so none
  was run for real.** Treat their parsers as unverified until run on a host that has them.
- ❌ GUI for managing tracked project dirs — CLI only (`projects add|remove`)

## What the Next Agent Should Do First
1. Run Snap/Nix/Distrobox/Homebrew/Conda on a machine that has them and compare real output against the
   parsers (`snap`, `nix`, `distrobox`, `brew`, `conda` drivers). Highest-risk guesses: `nix profile list
   --json` shape across versions, `brew search` non-TTY output, `conda search --json` error body,
   `bun`'s `-g` behaviour (`bun update -g` was not run).
2. Decide whether to add a GUI control for tracked project directories.
3. Respect these decisions: query commands go through `run_capture`; `check_updates` raising
   `NotImplementedError` means "unsupported", not failure; multi-target drivers (uv, Go, Bun, Bundler)
   raise only when *every* lookup failed and otherwise return partial results; Bundler/Gradle upgrade one
   project per command (a command is a single argv) and refuse ambiguous selections.

## Blocking Issues
None.

Known gaps: the TUI detail pane still labels an unsupported manager (Deno) "Up to date" because it only
distinguishes empty vs. non-empty updates. `assets/polyget.desktop` in the repo still points at
`~/Projects/Polyget/` (wrong case); only the installed copy in `~/.local/share/applications` was fixed.

## Build / Test Status
- Build: ✅ GUI launches offscreen with all 27 drivers (no traceback); TUI imports and scans headless
- Lint:  ✅ no pyflakes/syntax errors in changed files. The repo has no ruff config, so the global rule
  set flags ~280 style issues repo-wide; none were introduced as real defects (2 pre-existing F401s in manager.py)
- Tests: ✅ 302 passed, 0 failed
