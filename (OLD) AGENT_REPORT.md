# Agent Report

## Summary
Branch `CachyOS/BETA-FEATURES` (CachyOS desktop, Arch, x86_64). `master` is untouched at `ad511b1`. Nothing from this turn is pushed.

**This turn**
- **Fixed a false claim of mine:** the GUI did not show the detected architecture, because `scan_all()` clears the console right after
  startup. The line is now logged inside `scan_all()` after the clear (`app/ui/main_window.py`). New test
  `test_gui_console_shows_detected_system_after_the_scan_clears_it` fails against the old placement.
- **Peer access:** established ssh in both directions over Tailscale (`asahi` <-> `da-nvme`, user `daripper`). Inspected Asahi's repo
  **read-only**. Findings are in `docs/reports/ASAHI-READ-ONCE-2026-10-16.md` section 2a: Asahi `master` == `ad511b1`, but 27 uncommitted
  entries (+672/-162 tracked) that exist only on that laptop; merging this branch into that state conflicts in exactly four files
  (`app/cli.py`, `app/core/settings_store.py`, `app/ui/main_window.py`, `tests/conftest.py`).
- **New scripts:** `scripts/peer-snapshot.sh` (dry-run by default; `--git` fetches committed branches, `--go` mirrors the working tree
  read-only into `~/Projects/_devices/<peer>/PolyGet`; refuses any destination inside a working repo) and `scripts/setup-machine.sh`
  (per-clone merge rule so each machine keeps its own `AGENT_REPORT.md`).
- **Local, uncommitted-to-git effects on this machine:** created `~/Projects/_devices/asahi/` (read-only snapshot of Asahi's working tree,
  provenance in `SNAPSHOT_INFO.txt`).
- **Docs:** `BRANCHING.md` (identity table, sharing rules, what never to sync); read-once report (measured Asahi findings, merge preview,
  section 12 on what not to sync, corrected GUI statement); stale test counts fixed (222 -> 325) in the two older reports.

Earlier turns: 12 drivers, run_capture/fetch_json, project dirs + `projects` command, "unsupported is not failed" scan semantics, CPU
architecture detection (`app/core/arch.py`, catalog `arch` + arch-qualified install keys, `system` command), BRANCHING.md, pre-push guard.

## Feature / Task Status
- OK Architecture detection incl. GUI display (now actually shown and tested)
- OK Peer snapshot + merge-rule scripts, tested (dry run, real snapshot, guard refusal, merge-driver behavior in scratch repos)
- OK 12 new drivers: AUR, uv, Go, Bundler, Gradle verified against real tools on x86_64
- PARTIAL Snap, Nix, Distrobox, Homebrew, Conda, Bun: fixture-verified only
- PARTIAL Per-tool architecture facts: mechanism exists, no `arch:` lists filled in (Asahi owns the aarch64 facts)
- OPEN The `AGENTS.md` question (see below): no decision yet, file untouched
- NOT DONE Anything verified on aarch64 / the M1; GUI for tracked project dirs; the optional pre-push extension

## What the Next Agent Should Do First
1. Get the user's decision on `AGENTS.md` (protected file; byte-identical on master, this branch, and Asahi today). Recommended: keep the
   multi-machine rules in `BRANCHING.md` and append the same short pointer block to `AGENTS.md` on BOTH machines (identical text merges
   cleanly). Do not edit it without that approval.
2. Do not push until the user says so. Do not write anything to Asahi (all inspection so far was read-only).
3. Asahi agents: read `docs/reports/ASAHI-READ-ONCE-2026-10-16.md` once, then follow its section 7; resolve the four conflicts by keeping
   both sides (section 2a).
4. Keep the contracts: `[]` = ran and found nothing / `DriverError` = query broke / `NotImplementedError` = unsupported (not failure); one argv
   per upgrade; catalog `name` == driver `name`; `arch:` lists only for architectures verified on real hardware.

## Blocking Issues
None. Open decision: `AGENTS.md` approach. Unverified: everything on aarch64; Snap/Nix/Distrobox/Homebrew/Conda/Bun on real binaries.
Known gaps: TUI detail pane shows an unsupported manager as "Up to date"; `assets/polyget.desktop` still has the wrong-case path; new tests
live in `test_arch.py`/`test_cli_projects.py` rather than `test_cli.py` as `CLAUDE.md` prefers.

## Build / Test Status
- Build: OK GUI launches offscreen and the console shows the system line; TUI header shows the architecture
- Lint:  OK no pyflakes/syntax errors in changed files (repo has no ruff config; ~280 style findings repo-wide are pre-existing)
- Tests: OK 325 passed, 0 failed (master baseline: 222). x86_64 only; nothing run on aarch64.
