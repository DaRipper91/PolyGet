# Agent Report

## Summary
Branch `CachyOS/BETA-FEATURES` (CachyOS desktop, Arch, x86_64). `master` is untouched at `ad511b1`. **Nothing from the last two turns is pushed.**

**This turn**
- **`AGENTS.md` (option 2, approved by the user):** appended one marked pointer block (`polyget:multi-machine`) that sends agents to
  `BRANCHING.md`. Verified in scratch clones that the identical block added independently on both machines merges with no conflict.
  The exact text for Asahi is in `docs/reports/ASAHI-READ-ONCE-2026-10-16.md` section 14.A. `CLAUDE.md` untouched.
- **Branch naming settled:** the Asahi beta is `Asahi/BETA-FEATURES` (BRANCHING.md and both handoff reports updated).
- **Section 14 of the read-once report:** how Asahi adopts this ruling adapted for its own system (aarch64/M1/Fedora) and its own
  governance of `master`, with an adopt-as-is vs adapt table. Explicitly says NOT to install the `pre-push` guard on Asahi.
- **Merge preview redone at the current head** (scratch clones only): conflicts in exactly three files (`app/cli.py`,
  `app/core/settings_store.py`, `tests/conftest.py`); `AGENTS.md`, `app/core/manager.py`, `app/ui/main_window.py` auto-merge.
  An earlier "four files" figure in the docs was corrected.
- `BRANCHING.md`: pointer/shared-vs-per-machine sections. Earlier this session: GUI system-line fix (+test), `scripts/peer-snapshot.sh`,
  `scripts/setup-machine.sh`, `~/Projects/_devices/asahi/` read-only snapshot, ssh verified both ways over Tailscale.

Earlier work: 12 drivers, run_capture/fetch_json, project dirs, "unsupported is not failed" scan semantics, CPU architecture detection.

## Feature / Task Status
- OK Architecture detection incl. GUI display (tested)
- OK Multi-machine workflow docs, identity table, sharing rules, AGENTS.md pointer, peer scripts
- OK 12 new drivers: AUR, uv, Go, Bundler, Gradle verified against real tools on x86_64
- PARTIAL Snap, Nix, Distrobox, Homebrew, Conda, Bun: fixture-verified only
- PARTIAL Per-tool architecture facts: mechanism exists, none filled in (Asahi owns aarch64 facts)
- NOT DONE Anything verified on aarch64/M1; GUI for tracked project dirs; optional pre-push extension

## What the Next Agent Should Do First
1. Do not push until the user says so. Do not write anything to Asahi; inspect it read-only (`scripts/peer-snapshot.sh`).
2. Asahi agents: read `docs/reports/ASAHI-READ-ONCE-2026-10-16.md` once; follow section 7, then section 14 (append the `AGENTS.md`
   block byte-for-byte, with the user's approval, BEFORE merging). Keep both sides on the three conflicting files (section 2a).
3. Keep the contracts: `[]` ran and found nothing / `DriverError` query broke / `NotImplementedError` unsupported; one argv per
   upgrade; catalog `name` == driver `name`; `arch:` lists only for architectures verified on real hardware.

## Blocking Issues
None. Asahi has ~27 uncommitted entries that exist only on that laptop (a data-loss risk the user may want to address).
Known gaps: TUI detail pane shows an unsupported manager as "Up to date"; `assets/polyget.desktop` still has the wrong-case path.

## Build / Test Status
- Build: OK GUI launches offscreen, console shows the system line; TUI header shows the architecture
- Lint:  OK no pyflakes/syntax errors in changed files (no ruff config in the repo; ~280 pre-existing style findings)
- Tests: OK 325 passed, 0 failed (master baseline: 222). x86_64 only.
