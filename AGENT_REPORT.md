# Agent Report

## Summary
Machine: CachyOS desktop (x86_64, arch). Branch `CachyOS/BETA-FEATURES` is pushed through `9414a8a`. This file is the only change not pushed.

**Asahi published the stable.** GitHub `master` is now `dfea6a5` ("Add upgrade verification, settings page, tray, touch mode, skip version"),
Asahi's former local commit, and `Asahi/BETA-FEATURES` (`417accc`) exists. Local `master` was fast-forwarded to match.

**This turn: tested the stable here, then built a stable candidate.**
- Stage 1: `dfea6a5` unmodified on CachyOS: **226 passed**; real CLI, offscreen GUI and managers all fine. No errors found in the stable.
- Stage 2: local branch `CachyOS/stable-candidate` (worktree `~/Projects/PolyGet-stable-candidate`, commit `dbd1fbc`) = `master` + this beta's feature
  changes, with the governance files left out (BRANCHING.md, AGENTS.md pointer, agent reports, docs/reports, repo-check/peer-snapshot/setup-machine
  scripts, pre-push hook, test_repo_check). Made with `git merge --squash`, so it claims no ancestry from the beta.
- Conflicts (exactly the three predicted): `tests/conftest.py` (kept Asahi's HOME isolation + added the scripted-subprocess fixture),
  `app/core/settings_store.py` (kept both defaults), `app/cli.py` (semantic merge: my guarded step loop feeding Asahi's `verify=` call).
- **Bug found at the seam:** the stable's new confirm-commands code built every queued upgrade command in one unguarded comprehension, so a manager
  that cannot build one (Bundler across projects, Go with nothing installed, Deno) would have broken the dialog. Fixed; regression test fails without it.
- Stage 3: candidate **330 passed**; real CLI full `outdated` scan exits 0 over 13 managers (Deno reported as unsupported, not failed); real GUI scan with
  isolated HOME finished with 0 error lines and shows the system line; headless TUI scan fine.
- Comparison facts: Asahi's `AGENTS.md` pointer block is byte-identical to ours. Asahi's `ASAHI.md` says master is "owned by this laptop" and not to
  install the pre-push guard, which DISAGREES with our co-ownership wording in `BRANCHING.md`; its own text says to ask the user.

## Feature / Task Status
- OK Stable `dfea6a5` verified on CachyOS (226 tests, real CLI/GUI)
- OK Stable candidate built, resolved, tested, smoke-tested here (local, not pushed)
- OPEN Candidate not pushed; the user decides. Beta not yet merged with the new master.
- OPEN Governance disagreement (co-owned vs Asahi-owned master) needs the user
- NOT DONE Nothing verified on aarch64; Snap/Nix/Distrobox/Homebrew/Conda/Bun still fixture-only

## What the Next Agent Should Do First
1. `scripts/repo-check.sh --peer asahi`; do not write to Asahi; do not push without the user's say-so.
2. Candidate lives at `~/Projects/PolyGet-stable-candidate` (branch `CachyOS/stable-candidate`). Run tests with the main venv:
   `PYTHONPATH=. QT_QPA_PLATFORM=offscreen ~/Projects/PolyGet/.venv/bin/python -m pytest -q`.
3. To bring the beta up to the new master: merge (not rebase) `origin/master` into `CachyOS/BETA-FEATURES`; `rerere` already holds the resolutions.
4. Asahi must still test the candidate's feature set on aarch64/Fedora before anything is promoted to `master`.

## Blocking Issues
None. Open decisions: push the candidate? merge master into the beta? who owns master (see above)?

## Build / Test Status
- Build: OK (GUI/TUI/CLI run on the candidate)
- Lint:  OK no pyflakes/syntax errors in changed files (repo has no ruff config)
- Tests: stable 226 passed; candidate 330 passed; beta branch 338 passed (includes 13 governance tests). x86_64 only.
