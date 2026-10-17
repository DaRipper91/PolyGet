# Driver Expansion Report — 2026-10-16

> **Numbers in this report are as of commit `2e86ecc` (the drivers commit).** Later commits added architecture detection and
> more tests: the branch now has **325** passing tests (baseline `master`: 222). For the current picture read
> `ASAHI-READ-ONCE-2026-10-16.md` in this folder.

PolyGet went from **15 to 27 package-manager drivers**, with the shared plumbing they need.
Tests went from **222 to 302 passing**, with no regressions.

## 1. Where this started

The repo was cloned to `~/Projects/PolyGet` and the app menu entry repaired. The installed
`~/.local/share/applications/polyget.desktop` pointed at `~/Projects/Polyget/` (lowercase g)
and Linux paths are case-sensitive, so the launcher hid it through the failing `TryExec`.
The path was corrected, a `.venv` was created, and the app was launched through the entry.

Package search already existed (Store tab in the GUI, `search` in the CLI). The follow-up
question was which managers were missing. Cross-checking the 32-entry catalog, the driver
directory, and the binaries on this machine produced the list below.

## 2. What was added

| Driver | Category | Updates from | Notes |
|---|---|---|---|
| AUR | System | `paru -Qua` / `yay -Qua` | paru preferred, yay fallback. Never wrapped in `pkexec` (makepkg refuses root). Search is AUR-only (`-Ssa`). |
| uv | Language/Dev | PyPI JSON per tool | Search deliberately unsupported: Pipx already searches PyPI. |
| Go | Language/Dev | `go list -m <mod>@latest` | Packages are identified by import path, which is what `go install <path>@latest` needs. No search API. |
| Bun | Language/Dev | npm registry per package | Reads Bun's global `package.json` from disk (see 4.1). |
| Deno | Language/Dev | not supported | Lists installed scripts, installs, searches JSR. |
| Bundler | Language/Dev | `bundle outdated --parseable` | Per-project; see section 3. |
| Gradle | Language/Dev | wrapper version vs services.gradle.org | Per-project; upgrades via `gradlew wrapper --gradle-version latest`. |
| Snap | Universal | `snap refresh --list` | Upgrade/install via `pkexec`. |
| Nix | Universal | not supported | `nix profile` list/install/upgrade; search returns installable `nixpkgs#name` refs. |
| Distrobox | Universal | not supported | The managed unit is the container; "install" creates one from an image. |
| Homebrew | Universal | `brew outdated --json=v2` | One driver for macOS Homebrew and Linuxbrew. Casks only on macOS. Taps exposed as repos. |
| Conda | Language/Dev | `conda update --all --dry-run --json` | Also drives mamba. Operates on the base/active environment. |

## 3. Design decisions

**Bundler and Gradle.** The catalog had deliberately left both without drivers because their
scope is per project (`Gemfile.lock`, `build.gradle`) and PolyGet has no project concept. The
chosen design keeps that honest:

- Projects are registered with `python run.py projects add DIR`, stored under `projects.dirs` in
  `~/.config/polyget/settings.json`.
- The drivers report unavailable until a matching project is tracked, so an unconfigured install
  shows nothing instead of a false "all up to date".
- Update names encode the owning project (`rake @ /path/to/app`).
- A command is a single argv, so an upgrade can only act on one project. A selection spanning
  several projects is refused with an error rather than upgrading one silently.
- Bundler targets a project with `env BUNDLE_GEMFILE=<dir>/Gemfile bundle update`, avoiding any
  need for a working directory. Gradle uses its built-in wrapper upgrade path, since Gradle has no
  built-in dependency-update command.

**Three-way contract for "I can't tell you".** `[]` means the query ran and found nothing.
`DriverError` means the query broke. `NotImplementedError` means the manager cannot answer this
question. The scanners previously treated any exception from `check_updates` as a failure, which
would have made Deno, Nix, and Distrobox turn every scan red. The CLI, GUI, and TUI now treat
`NotImplementedError` as "unsupported": reported, but not a failure.

**Partial results.** Drivers that query many targets (uv, Go, Bun, Bundler) raise only when every
lookup failed. If some succeed, those results are returned. The trade-off: a single flaky lookup
no longer hides the rest, but an individual failed package can be missing from the results.

**Shared helpers, existing drivers untouched.** `run_capture()` and `fetch_json()` in
`app/core/manager.py` replace roughly 15 lines of subprocess boilerplate per query. The 15
existing drivers were not refactored.

## 4. Problems found along the way

1. **`bun pm ls -g` falls back to the current directory.** When Bun's global directory does not
   exist, it silently lists the working directory's `node_modules`. In `~` that would have shown
   33 unrelated npm packages as "global Bun packages". The driver reads
   `$BUN_INSTALL/install/global/package.json` directly and never shells out for this.
2. **The built `deno` has no `upgrade`.** The Arch-packaged build ships without the feature, so
   Deno cannot update itself or report outdated scripts portably. This is why Deno is
   list/install/search only.
3. **Catalog name invariant.** `test_catalog_driver_consistency` requires a catalog entry's name
   to equal its driver's name. It caught `Paru (AUR helper)` and `Go Modules`. They became `AUR`
   and `Go`; the separate yay entry was folded into AUR.
4. **Unguarded command builders.** `get_upgrade_command()` is called unguarded in the CLI, the GUI
   upgrade queue, and twice in the TUI (including a detail pane that renders for every manager).
   Drivers that may legitimately raise would have crashed those paths, so each now catches
   `NotImplementedError`/`DriverError` and reports it.
5. **A wrong test needle, not a driver bug.** The Nix search test failed because the real argv has
   `--extra-experimental-features` between `nix` and `search`. The test was fixed.

## 5. Verification

| Check | Result |
|---|---|
| Baseline before any change | 222 passed |
| Final | **302 passed**, 0 failed |
| AUR, uv, Go | Run against the real tools: 42 AUR packages; uv found `hcom 0.7.25 → 0.7.30` and `litellm 1.103.0 → 1.105.1`; Go reported `tailcat` current |
| Bundler, Gradle | Run against throwaway projects with real `bundle` and `gradle`: `rake 12.3.3 → 13.4.2`, wrapper `8.5 → 9.8.1`; the multi-project guard refused correctly |
| `gradle wrapper --gradle-version latest` | Confirmed as a documented label via `gradle help --task wrapper` |
| GUI | Launched offscreen with all 27 drivers for 25 s, no traceback |
| TUI | Driven headless with Textual's test harness; Deno was skipped quietly, `scan_errors` empty |
| Lint | No pyflakes/syntax errors in changed files. The repo has no ruff config, so the global rule set flags about 280 style issues repo-wide; the 2 real `F401`s are pre-existing in `manager.py` |

**Not verified against real binaries:** Snap, Nix, Distrobox, Homebrew, and Conda are not installed
on the development machine. Their parsers are tested against fixtures built from each tool's
documented output only. Bun is also fixture-only, because no global Bun packages exist here, and
`bun update -g` was never run.

## 6. Known gaps and follow-ups

1. Run the five unverified drivers on hosts that have them and compare real output with the parsers.
   Highest-risk guesses: the `nix profile list --json` shape across versions, `brew search`
   non-TTY output, and the `conda search --json` error body.
2. There is no GUI for managing tracked project directories (CLI only).
3. The TUI detail pane labels an unsupported manager (Deno) "Up to date", because it only
   distinguishes empty from non-empty update lists.
4. `assets/polyget.desktop` in the repo still points at `~/Projects/Polyget/` (wrong case). Only the
   installed copy was fixed.
5. Homebrew has no self-install entry: the official installer is a curl-piped shell script and cannot
   be expressed as a safe argv. Install it from brew.sh.

## 7. File inventory

**New:** `app/core/drivers/{aur,uv,go,bun,deno,bundler,gradle,snap,nix,distrobox,brew,conda}.py`,
`app/core/projects.py`, `tests/conftest.py`, and nine test files covering the helpers, every new
driver, and the CLI changes.

**Modified:** `app/core/manager.py`, `app/core/settings_store.py`, `app/core/distro.py`,
`app/core/data/manager_catalog.yaml`, `app/cli.py`, `app/ui/main_window.py`, `app/ui/tui.py`,
`README.md`. `AGENT_REPORT.md` was added per the repo's reporting rules.
