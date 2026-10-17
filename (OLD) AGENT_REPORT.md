# Agent Report

## Summary
Machine: CachyOS desktop (x86_64, arch). Branch `CachyOS/BETA-FEATURES`: GitHub has `9414a8a`; this machine holds unpushed local commits
(the agent-report updates and this turn's work). `master` on GitHub is `dfea6a5` (Asahi's stable). Asahi's beta is on GitHub at `9b82358`.

**This turn: a way for Asahi to review the stable candidate through the shared mount, plus a report for it.**
- Mount facts: the machines cross-mount each other's home over sshfs (`~/remotes/asahi` here, `~/remotes/da-nvme` on Asahi); read-write, noexec.
  The live candidate worktree is a poor review target (its `.git` points at a path that exists only here), so a plain read-only export is used.
- `scripts/review-export.sh` (new): rebuilds `~/Projects/_review/<branch>-<sha>/` (files/, patch vs base, diffstat, README, optional REPORT.md),
  read-only, with a relative `<branch>-latest` symlink; skips an unchanged commit, prunes only that branch's older exports, warns if governance
  files leak in, aborts if `.git`/`.venv` do. `tests/test_review_export.py`: 10 tests with real git.
- `docs/reports/ASAHI-REVIEW-CANDIDATE-2026-10-17.md` (new): the status report and review request for Asahi (branch map, what the candidate is,
  conflict resolutions, the seam bug, test evidence, an aarch64/Fedora checklist, the three read-only routes, an audit of every action taken on
  Asahi, honest limits). It is also copied into the export as `REPORT.md`.
- Verified from Asahi's side with read-only commands: the `-latest` link resolves, hashes match, 145 files, `git ls-remote` sees `dbd1fbc`.
  The patch-applies check was run HERE. (Last turn I created one temp dir under Asahi's /tmp for a check; Asahi's newer rule forbids writes, so I
  stopped and disclosed it in the report.)
- Asahi moved on: `9b82358` dropped the master freeze and added a read-only-home rule; its `BRANCHING.md` no longer hashes to the file the user
  hand-delivered (`0d2d96d9…` -> `e9945a2d…`). Measured: taking Asahi's file wholesale loses only the 3 superseded new-manager lines.
  I applied NOTHING from that file; this beta's `BRANCHING.md` is unchanged.

Earlier: stable `dfea6a5` verified on CachyOS (226 passed); candidate `dbd1fbc` built (local branch `CachyOS/stable-candidate`, 330 passed);
12 drivers, architecture detection, co-ownership docs, repo-check, peer snapshots.

## Feature / Task Status
- OK Review export script + tests + Asahi report, verified end to end across the mount
- OK Candidate built and verified on CachyOS; NOT on aarch64/Fedora
- OPEN Push decisions: the beta's unpushed commits and the candidate (local only) wait for the user
- OPEN `BRANCHING.md` sync (take Asahi's file wholesale) and merging `origin/master` into the beta wait for the user
- NOT DONE Snap/Nix/Distrobox/Homebrew/Conda/Bun on real binaries; anything on aarch64

## What the Next Agent Should Do First
1. `scripts/repo-check.sh --peer asahi`; read-only toward Asahi (no writes, no temp dirs, `git --no-optional-locks`). Do not push without the user.
2. After any change to the candidate: `scripts/review-export.sh --force --report <report> --tested "<what you ran>"`.
3. Asahi agents: read `~/remotes/da-nvme/Projects/_review/CachyOS-stable-candidate-latest/REPORT.md` first; follow its section 7 checklist locally.
4. Keep the contracts: `[]` ran and found nothing / `DriverError` query broke / `NotImplementedError` unsupported; catalog `name` == driver `name`.

## Blocking Issues
None. Open decisions are the push / merge / BRANCHING-sync items above.

## Build / Test Status
- Build: OK (CLI/GUI/TUI ran on the candidate); review export verified from Asahi
- Lint:  OK no pyflakes/syntax errors in changed files (no ruff config in the repo)
- Tests: OK 348 passed on the beta (candidate: 330, stable alone: 226). x86_64 only.
