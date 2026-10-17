# Agent Report

## Summary
Machine: CachyOS desktop (x86_64, arch). **GitHub `master` is now `c1d38e8`** (promoted from `CachyOS/stable-candidate`). `CachyOS/BETA-FEATURES` on GitHub is still `9414a8a`;
this machine holds 4 unpushed local commits on it (including this one). `Asahi/BETA-FEATURES` is `9b82358`.

**This turn: the user said "promote that to master, apply the edits, then suggest what's next."**
- **Promotion (user-approved, explicit):** pre-flight first: `repo-check --promoting --peer asahi` had no ALERT; Asahi clean and in sync at `dfea6a5`; the candidate was a pure
  fast-forward of 2 commits (35 files), no governance files, `AGENTS.md` untouched; 353 passed on the exact commit; the 4 pyflakes hits already existed on master (0 new).
  Pushed `CachyOS/stable-candidate:master` through the guarded hook with the deliberate override (`dfea6a5..c1d38e8`). Verified: master's tree == the candidate's tree.
  **Unmet checklist item, disclosed:** "tests green on both machines" was met for `dbd1fbc` on the M1 (330 passed, per Asahi) but NOT yet for `c1d38e8`; the user approved anyway.
  Local `master` fast-forwarded. Asahi's local master is now 2 behind (repo-check flags it); I do not write to Asahi.
- **BRANCHING.md edits applied** on the beta (the 3 edits from the note): the note's own assert passed and the file hashes to `e9945a2d…`, byte-identical to Asahi's pushed `9b82358` (0-line diff).
  The two older CachyOS reports were reworded to the new check-it-yourself rule for new managers.
- The Asahi report (`docs/reports/ASAHI-REVIEW-CANDIDATE-2026-10-17.md`) now opens with a PROMOTED banner and tells Asahi to fast-forward its master and re-run `c1d38e8` on the M1
  as a post-promotion verification (rollback = a revert commit, never a force-push). Export rebuilt and verified from Asahi's side (hashes match).
- Measured for "what's next": merging `origin/master` into this beta conflicts in 6 files (cli.py, uv.py, settings_store.py, main_window.py, tests/conftest.py, tests/test_uv_driver.py)
  because the candidate was squashed; master's versions are newer, so they resolve by taking master's side.

## Feature / Task Status
- OK Candidate promoted to master and verified landed exactly; BRANCHING.md synced to Asahi's copy
- OPEN `c1d38e8` on aarch64 (Asahi); merging master into this beta; pushing this beta; cleaning up the candidate branch/worktree/export
- NOT DONE Homebrew/Conda/Deno/Distrobox/Nix on real binaries; Pipx local-source exposure; `arch:` data; GUI for tracked project dirs

## What the Next Agent Should Do First
1. `scripts/repo-check.sh --peer asahi` (read-only toward Asahi: no writes, no temp files; ssh via `bash -s`; `git --no-optional-locks`). Never push without the user; master pushes need the deliberate override.
2. Expected until Asahi acts: Asahi's local master is behind `origin/master`. That is its to fix.
3. The merge of master into this beta: take master's side for the 6 feature files; keep the beta's governance files.
4. Keep the contracts: `[]` ran and found nothing / `DriverError` query broke / `NotImplementedError` unsupported; catalog `name` == driver `name`.

## Blocking Issues
None. Open: the M1 verification of c1d38e8, and the user's decisions on the suggestions below.

## Build / Test Status
- Build: OK (candidate CLI/GUI/TUI verified before promotion)
- Lint:  OK no new findings (the 4 pyflakes hits pre-date the promotion and exist on master)
- Tests: OK 348 passed on this beta; master (== candidate) 353 on CachyOS; Asahi reports 330 passed for dbd1fbc on the M1. x86_64 only for c1d38e8.
