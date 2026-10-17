# Agent Report

## Summary
Branch `CachyOS/BETA-FEATURES` (CachyOS desktop, x86_64). Pushed so far: through `1fd1012`. `master` on GitHub is still `ad511b1`.
**Everything from this turn is local and unpushed (it changes policy, so it needs the user's go-ahead).**

- **Master co-ownership** (the user's direction): `master` is co-owned by both machines; each beta branch has exactly one owner.
  `BRANCHING.md` gains "Who owns what", "Start of every session: run the repo check", an identity table that no longer says "never master",
  and a rewritten guard section. Every "Asahi owns master" / "do not install the guard on Asahi" statement in the docs was updated.
- **`scripts/repo-check.sh`** (new, read-only apart from `git fetch`): flags local `master` != `origin/master` (and, the key case, a beta
  that matches its remote while master does not), a beta behind `origin/master`, unpushed commits, uncommitted work, diverged branches,
  and with `--peer <host>` the other machine's master / uncommitted work. Exit 0 clean / 1 review suggested / 2 alert.
  `--promoting` mode treats "local master ahead" as expected and "behind" as an alert. Verified by a 10-scenario matrix and 13 pytest tests.
- **Real finding:** pointing it at Asahi showed that the laptop's work is now a local commit, `dfea6a5` ("Add upgrade verification, settings
  page, tray, touch mode, skip version", 27 files, +735/-162), NOT pushed; GitHub's master is still `ad511b1`. Merging this branch with that
  real commit conflicts in exactly three files: `app/cli.py`, `app/core/settings_store.py`, `tests/conftest.py`.
- **`scripts/git-hooks/pre-push`** reworked: master pushes need a deliberate override, the override still runs `repo-check --promoting` and
  refuses on ALERT, and it **fails closed** if the script is missing. My own tests exposed that the first version silently skipped the check
  when `master` lacked the script. Also learned: git rejects non-fast-forward pushes before any hook runs, so the hook's real value is
  against forced pushes.
- **Fixed in both `repo-check.sh` and `peer-snapshot.sh`:** Asahi's login shell is fish, which broke a bash-style ssh one-liner. Remote
  commands now go through `bash -s` on stdin.
- `tests/test_repo_check.py` (13 tests, real git against simulated machines); stale architecture wording in BRANCHING.md corrected;
  `~/Projects/_devices/asahi/` snapshot refreshed.

Earlier: 12 drivers, architecture detection (`app/core/arch.py`), project dirs, AGENTS.md pointer block (pushed), Asahi read-once report.

## Feature / Task Status
- OK Repo-drift check + promotion-aware mode + fail-closed push guard, tested
- OK Co-ownership documented consistently
- OK Architecture detection, 12 drivers (AUR, uv, Go, Bundler, Gradle verified on real tools; others fixture-only)
- OPEN User must confirm the co-ownership policy and say whether to push this turn's commit
- NOT DONE Anything verified on aarch64/M1; GitHub branch protection (a remote setting); GUI for tracked project dirs

## What the Next Agent Should Do First
1. Run `scripts/repo-check.sh --peer asahi` (from Asahi: `--peer da-nvme`) before anything else. Do not write to the other machine.
2. Do not push until the user says so. Do not merge anything into `master` outside the promotion steps in `BRANCHING.md`.
3. Asahi agents: read `docs/reports/ASAHI-READ-ONCE-2026-10-16.md` once, follow section 7 then section 14; resolve the three conflicts by
   keeping both sides; Asahi's `dfea6a5` still needs a decision (push as a fast-forward, or onto `Asahi/BETA-FEATURES`).
4. Keep the contracts: `[]` ran and found nothing / `DriverError` query broke / `NotImplementedError` unsupported; catalog `name` ==
   driver `name`; ssh to either machine goes through `bash -s` because the login shell may be fish.

## Blocking Issues
None. Open: co-ownership policy confirmation and the push decision. Known gaps: TUI detail pane shows an unsupported manager as "Up to
date"; `assets/polyget.desktop` still has the wrong-case path; the hook's `master` gate is untested on aarch64.

## Build / Test Status
- Build: OK GUI launches offscreen and shows the system line; TUI header shows the architecture
- Lint:  OK no pyflakes/syntax errors in changed files (no ruff config in the repo)
- Tests: OK 338 passed, 0 failed (master baseline: 222). x86_64 only; nothing run on aarch64.
