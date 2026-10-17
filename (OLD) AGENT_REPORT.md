# Agent Report

## Summary
Branch `CachyOS/BETA-FEATURES` (CachyOS, Arch, x86_64). `master` is untouched at `ad511b1`.

**This turn: CPU-architecture detection, plus a read-once handoff for the Asahi agents.**
- `app/core/arch.py` (new): `normalize_arch()`, cached `get_machine_arch()` (`arm64`→`aarch64`, `amd64`→`x86_64`,
  `"unknown"` if unreadable), `describe_system()`.
- `app/core/catalog.py`: `CatalogEntry.arch` (optional; empty = unknown, never "verified everywhere"),
  `supports_this_arch()`, and `get_self_install_command()` now prefers arch-qualified keys (`fedora:aarch64`) and
  returns `None` when the entry excludes this machine.
- `app/cli.py`: new `system` command; `catalog` reports `arch` and `supported_on_this_arch`.
- `app/ui/main_window.py` logs the detected system at startup; `app/ui/tui.py` shows the architecture in the header.
- `app/core/data/manager_catalog.yaml`: header documents `arch:` and arch-qualified keys. No entry sets them yet.
- `tests/test_arch.py` (new, 22 tests; faking both architectures).
- `docs/reports/ASAHI-READ-ONCE-2026-10-16.md` (new): the complete context for the Asahi agents.
- `docs/reports/2026-10-16-cachyos-beta-handoff-for-asahi.md`: now points to the read-once file.
- `AGENT_REPORT.md` rotated to `(OLD) AGENT_REPORT.md` (the previous report covered the 12-driver work).

Earlier turns (details in `(OLD) AGENT_REPORT.md` and `docs/reports/2026-10-16-driver-expansion.md`): 12 new drivers
(AUR, uv, Go, Bun, Deno, Bundler, Gradle, Snap, Nix, Distrobox, Homebrew, Conda), `run_capture`/`fetch_json`, tracked
project dirs + `projects` command, "unsupported is not failed" scan semantics, `BRANCHING.md`, a local `pre-push` guard.

## Feature / Task Status
- ✅ Architecture detection (detect + expose + use in the catalog), unit-tested with both architectures faked
- ✅ 12 new drivers: AUR, uv, Go, Bundler, Gradle verified against real tools on x86_64
- 🔄 Snap, Nix, Distrobox, Homebrew, Conda, Bun: fixture-verified only; never run for real (not installed here)
- 🔄 Per-tool architecture facts: the mechanism exists but **no `arch:` lists or `:aarch64` keys are filled in**; only
  x86_64 can be verified from this machine. The Asahi side owns the aarch64 facts.
- ❌ Anything verified on aarch64 / the M1
- ❌ GUI control for tracked project directories (CLI only)

## What the Next Agent Should Do First
1. Run `git status`/`git log origin/master..HEAD` before anything: Asahi may be ahead of GitHub's `master` (`ad511b1`).
2. If you are an Asahi agent: read `docs/reports/ASAHI-READ-ONCE-2026-10-16.md` once, fully, then follow its section 7.
   Use a `git worktree` to review; do not pull this branch into a working branch; do not touch `master`.
3. Review the real code and run the suite (`PYTHONPATH=. .venv/bin/pytest -q`; `pytest` is not in `requirements.txt`).
4. Ask the user before checking for or installing any new manager. Never invent install commands.
5. Respect these decisions: `[]` = ran and found nothing / `DriverError` = query broke / `NotImplementedError` =
   unsupported (not a failure); one argv per upgrade, so per-project drivers upgrade one project at a time;
   catalog `name` must equal the driver `name`; arch lists contain only architectures verified on real hardware.

## Blocking Issues
None. Open decisions for the user are listed in section 11 of the read-once file.
Known gaps: TUI detail pane shows an unsupported manager as "Up to date"; `assets/polyget.desktop` still hard-codes
the wrong-case path `~/Projects/Polyget/`; new subcommand tests live in `tests/test_arch.py` and
`tests/test_cli_projects.py` rather than `tests/test_cli.py` as `CLAUDE.md` prefers.

## Build / Test Status
- Build: ✅ GUI launches offscreen with all 27 drivers (no traceback); TUI header renders with the architecture
- Lint:  ✅ no pyflakes/syntax errors in changed files (the repo has no ruff config; the global rule set flags ~280
  style issues repo-wide; two pre-existing intentional `F401`s in `manager.py`)
- Tests: ✅ 324 passed, 0 failed (baseline before any work this session: 222). x86_64 only; nothing run on aarch64.
