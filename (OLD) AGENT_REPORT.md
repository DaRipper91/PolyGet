# Agent Report

## Summary
Machine: CachyOS desktop (x86_64, arch). GitHub: `master` = `c1d38e8` (**now protected: PR required, enforced for admins**), `Asahi/BETA-FEATURES` = `9b82358`,
`CachyOS/BETA-FEATURES` = `9414a8a` (this machine is 10 commits ahead of that (3 of them came in from master: Asahi's dfea6a5 plus the two promoted commits; one is the merge itself)). Open PRs: **#2** `CachyOS/arch-verified-on`, **#3** `CachyOS/fix-pipx-updates` (neither merged).

**This turn: merge master into the beta, install the stable, require PRs, add arch info, skip item 7, figure out item 8.**
- **Merged master into the beta** (`b800adb`): 6 conflicts (squash leftovers), resolved by taking master's side after proving master already contains every line the beta added
  (except 2 superseded guard lines). The merged beta differs from master only by the 15 governance files; 376 tests pass.
- **Stable installed on this machine:** `~/Projects/PolyGet-stable` (worktree on `master`) with its OWN venv; `scripts/install-desktop.sh` re-pointed the launcher and icons;
  `~/.local/bin/polyget` re-pointed. Verified: 353 passed in that venv, launcher command starts offscreen. Found in passing: `pytest-asyncio` is not declared anywhere
  (a venv with only pytest fails 15 tests); the repo's own audit notes already flagged the missing `requirements-dev.txt`.
  To update: `git -C ~/Projects/PolyGet-stable pull --ff-only` after master moves.
- **Require PR on master:** GitHub branch protection set (PR required, 0 approvals, enforce_admins true, no force-push, no deletion) and read back. Behaviour NOT tested by a direct push
  (it would have changed master if it failed to bind). Relax with: `gh api -X DELETE repos/DaRipper91/PolyGet/branches/master/protection`. BRANCHING.md's four stale sentences corrected;
  a hash-verified change note for Asahi is at `~/Projects/_review/PolyGet-BRANCHING-change-for-asahi.md` (new hash 4496a597…; its script was run verbatim on a copy of Asahi's file and matched).
- **Arch info (PR #2):** a design flaw in my own earlier work was found and proven: `arch:` is a HARD FILTER, so recording "verified on x86_64" there would have marked NPM etc.
  unsupported on the M1 (no install offered). Added a separate informational `verified_on` field (+ `verified_on_this_arch` in `catalog`); x86_64 recorded for the 10 managers exercised with real data
  (pacman, aur, flatpak, npm, cargo, gem, uv, go, bundler, gradle); no aarch64 entries (Asahi's to add). 359 tests; a guard test fails if anything uses the `arch:` filter by accident.
- **Item 8 findings:** (a) **Pipx was reporting "up to date" while 3 apps were outdated** (ruff, suno-cli, uvicorn): the driver needed a per-venv `bin/pip` which current pipx venvs lack,
  and used a flag (`--json`) pip/uv reject. Fixed in **PR #3** (374 tests; 7 of 12 Pipx tests fail on the old driver) plus a local-source filter, reproduced in an isolated sandbox with a control.
  (b) GUI project dirs, (c) TUI "Up to date" for unsupported managers, (d) assets/polyget.desktop hard-coded `/home/daripper/Projects/Polyget`, (e) no requirements-dev.txt: assessed, not built.
- Slips owned: shell traps again (zsh does not word-split unquoted vars; fish login shell on Asahi); an escaped newline in a test; a duplicate import; I opened PR #2 before checking existing PRs (checked right after: #1 is an unrelated merged July PR).

## Feature / Task Status
- OK master merged into beta; stable installed; branch protection on; arch info as PR #2; Pipx fix as PR #3 (both unmerged by design)
- SKIPPED (user's choice) item 7: Homebrew/Conda/Deno/Distrobox/Nix on real binaries
- OPEN PRs #2 and #3 need the user's approval to merge; Asahi must fast-forward master and re-run c1d38e8 on the M1; push this beta (10 commits ahead of GitHub); item 8 (b)(c)(d)(e)

## What the Next Agent Should Do First
1. `scripts/repo-check.sh --peer asahi` (read-only toward Asahi, ssh via `bash -s`, `git --no-optional-locks`). master can only change through a PR the user approves. Never merge or push without the user.
2. Shell traps in this environment: the Bash tool is zsh (no word-splitting of unquoted vars: put logic in a script file or use `bash -c`); Asahi's login shell is fish (always `ssh host bash -s` with a heredoc).
3. This beta's BRANCHING.md now differs from Asahi's pushed copy ON PURPOSE (4 edits for branch protection); Asahi applies the note, then they match again.
4. Keep the contracts: `[]` ran and found nothing / `DriverError` query broke / `NotImplementedError` unsupported; catalog `name` == driver `name`; `arch:` filters, `verified_on:` records.

## Blocking Issues
None.

## Build / Test Status
- Build: OK (stable app verified from its own venv)
- Lint:  OK no new findings (4 pre-existing pyflakes hits on master)
- Tests: OK 376 passed on this beta; master 353; PR #2 branch 359; PR #3 branch 374. x86_64 only.
