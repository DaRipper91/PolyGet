# Agent Report

## STOPPING POINT (rate limit). Everything below is consistent and safe to resume from.

## Summary
Machine: CachyOS desktop (x86_64). GitHub: `master` = `c1d38e8` (protected: PR required, enforced for admins); `Asahi/BETA-FEATURES` `9b82358`;
`CachyOS/BETA-FEATURES` `9414a8a` (this clone is ahead by ~11 local commits, nothing pushed). **Open PRs: #2 (verified_on), #3 (Pipx fix). Neither merged.**

**Asahi has verified the promoted master on the M1:** its review doc (`~/Documents/PolyGet-review-of-stable-candidate-dbd1fbc.md` on Asahi, updated 01:31) reports
`c1d38e8`: **353 passed on aarch64**, `outdated` exit 0, `aether` gone, real `graphifyy` update still reported; Asahi's local master is already `c1d38e8`.
So the promotion checklist's "tests green on both machines" is now met for c1d38e8. Asahi's two optional notes: Retry re-queues an unbuildable manager (fixed in the
hygiene branch below); the Python 3.10 fallback in uv.py runs on neither machine (KEPT because the README promises 3.10+; the user can decide to drop it).

**Local, NOT pushed, NO PR yet: branch `CachyOS/hygiene-dev-reqs-tui-lint` (worktree `~/Projects/PolyGet-hygiene`, 1 commit on master c1d38e8).**
Contents: requirements-dev.txt + README line (pytest-asyncio was undeclared), TUI "Update check not supported" label (instead of "Up to date"), unbuildable managers named in the
upgrade dialog but not offered for Retry, F-level lint clean repo-wide (importlib in manager.py; 2 unused test names), assets/polyget.desktop made a template with a neutral
placeholder, tests for the installer. 360 passed on CachyOS; lint clean; no governance files.

Done earlier this session and verified: master merged into this beta (376 tests); stable installed from `~/Projects/PolyGet-stable` (own venv; launcher, icons and `polyget`
command point there); branch protection enabled; BRANCHING.md corrected for it + hash-verified change note for Asahi at `~/Projects/_review/PolyGet-BRANCHING-change-for-asahi.md`
(target sha256 4496a597…); PR #2 `verified_on` (x86_64 for 10 managers; `arch:` stays the hard filter); PR #3 fixes the Pipx driver that reported "up to date" while 3 apps were outdated.

## Feature / Task Status
- OK Stable on both machines: master c1d38e8 tested on CachyOS (353) and on the M1 (353, per Asahi)
- OK Hygiene branch committed locally and green
- OPEN (needs the user) merge PR #2 and PR #3; open + merge a PR for the hygiene branch; push this beta
- OPEN (Asahi) apply the BRANCHING.md note; add aarch64 to `verified_on` for what it verified; its section-9 folders (`_devices`, `_review`) wait on the user's confirmation
- NOT DONE GUI control for tracked project dirs (user's call); Homebrew/Conda/Deno/Distrobox/Nix on real binaries (user skipped); 9 older test files still emit un-awaited AsyncMock warnings (noise, not errors)

## What the Next Agent Should Do First
1. `scripts/repo-check.sh --peer asahi` (read-only toward Asahi; ssh only via `bash -s`; `git --no-optional-locks`). Never merge/push to master except by a user-approved PR.
2. Recommended order to finish "stable and error free on both devices": (a) integration-test master + PR #2 + PR #3 + the hygiene branch together in a scratch worktree; (b) open the hygiene PR; (c) with the user's go-ahead merge #2, #3, hygiene
   (`gh pr merge --merge`); (d) `git -C ~/Projects/PolyGet-stable pull --ff-only` and re-run tests there + a real CLI/GUI scan; (e) merge master into this beta, push it; (f) rebuild the Asahi export
   (`scripts/review-export.sh CachyOS/stable-candidate master --force --report docs/reports/ASAHI-REVIEW-CANDIDATE-2026-10-17.md --tested "..."`, then wait ~25 s) and ask Asahi to re-run the suite on the M1;
   (g) when Asahi confirms, delete the `CachyOS/stable-candidate` branch/worktree and old export.
3. Traps: the Bash tool is zsh (unquoted vars are not word-split: use a script file or `bash -c`); Asahi's login shell is fish; a fresh venv needs `pytest-asyncio`.

## Blocking Issues
None. Waiting only on the user's approvals above.

## Build / Test Status
- Build: OK (stable app verified from its own venv)
- Lint:  OK F-level clean on the hygiene branch (master has 4 pre-existing findings that branch removes)
- Tests: master 353 (CachyOS and M1); PR #2 branch 359; PR #3 branch 374; hygiene branch 360; this beta 376 (last run before the hygiene work). x86_64 except where Asahi's M1 result is noted.
