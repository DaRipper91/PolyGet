# Agent Report

## Summary
Machine: CachyOS desktop (x86_64, arch). `CachyOS/BETA-FEATURES`: GitHub has `9414a8a`; this machine holds unpushed local commits (nothing pushed this turn).
GitHub: `master` `dfea6a5` (Asahi's stable), `Asahi/BETA-FEATURES` `9b82358`.

**This turn: acted on Asahi's review of the stable candidate.**
- Found and read (read-only, over ssh) `~/Documents/PolyGet-review-of-stable-candidate-dbd1fbc.md` on Asahi. Verdict there: the candidate works on aarch64/Fedora
  (330 passed on the M1), two findings, and the user decided CachyOS fixes both on `CachyOS/stable-candidate`.
- **Finding 1 (uv, fixed):** tools installed from a directory/path/git/url/`editable` source were compared with an unrelated same-named PyPI project.
  `uv.py` now reads `uv-receipt.toml` (tomllib, with a bracket-aware text fallback for Python 3.10) and skips them with no lookup. Verified against
  the real receipts here (my own `agentdeck`/`hexmind` use `editable`, which the review's key list lacked; `aider-chat`'s receipt is multi-line);
  reproduced the false positive with the fix disabled. Pipx NOT changed (could not reproduce; stable's code).
- **Finding 2 (GUI, fixed):** an unbuildable upgrade now also lands in `upgrade_results` via `_record_unbuildable()`, so the end-of-run dialog and Retry
  include it; if every queued manager is unbuildable a warning dialog names them. 3 tests fail on the pre-fix code.
- Candidate is now `c1d38e8` (= `dbd1fbc` + one fix commit; 353 passed; lint clean; no governance files; real CLI exit 0, real GUI scan 0 errors).
- **Agreement (user): peer access is strictly read-only both ways, no exception for temp files.** Measured: /tmp is RAM-backed tmpfs on both machines
  (Asahi 3.7 GiB cap, ~3.2 GiB free of 7.3); both run uid 1000 over rw sshfs, so it is an agreement not an enforced boundary.
- `scripts/review-export.sh`: README fetch hint now follows PEER_MOUNT (it hard-coded da-nvme, wrong for exports made on Asahi); added a note about the
  ~20 s sshfs cache (measured: Asahi saw a stale -latest link right after a rebuild, correct 15 s later).
- `docs/reports/ASAHI-REVIEW-CANDIDATE-2026-10-17.md` rewritten (v2): response to the review, corrected numbers, the read-only agreement, an audit of every
  action on Asahi, and **section 9: instructions for Asahi to create its own `~/Projects/_devices/` and `~/Projects/_review/`** (the user asked for this).
  Export rebuilt at `c1d38e8` and verified from Asahi with read-only commands (hashes match, 145 files).
- Slips owned: I again sent a bash-style one-liner over ssh to a fish login shell (always use `bash -s` on stdin); one duplicate import caught by lint
  and fixed before sharing. Earlier: one temp dir on Asahi's /tmp (disclosed; will not recur).

## Feature / Task Status
- OK Both review findings fixed, tested, verified on real CachyOS tools; export rebuilt and verified from Asahi's side
- OK Report for Asahi (v2) with folder-setup instructions
- OPEN `c1d38e8` on aarch64 (Asahi re-runs); push decisions (beta commits, candidate); `BRANCHING.md` sync (3 edits, hash e9945a2d… matches Asahi's pushed 9b82358; NOT applied)
- NOT DONE Homebrew/Conda/Deno/Distrobox/Nix on real binaries (absent on both machines); Pipx local-source exposure

## What the Next Agent Should Do First
1. `scripts/repo-check.sh --peer asahi`. Read-only toward Asahi, no exceptions (no temp files); use `bash -s` for ssh; `git --no-optional-locks`. Never push without the user.
2. After any candidate change: `scripts/review-export.sh CachyOS/stable-candidate master --force --report <report> --tested "<what ran>"`, then wait ~25 s before verifying from Asahi.
3. Waiting on the user: apply the 3 `BRANCHING.md` edits? merge `origin/master` into the beta? push the beta / the candidate?
4. Keep the contracts: `[]` ran and found nothing / `DriverError` query broke / `NotImplementedError` unsupported; catalog `name` == driver `name`.

## Blocking Issues
None. Open decisions are the push / merge / BRANCHING-sync items above.

## Build / Test Status
- Build: OK (candidate CLI/GUI/TUI run clean; review export verified from Asahi)
- Lint:  OK no pyflakes/syntax errors in changed files (no ruff config in the repo)
- Tests: OK 348 passed on the beta; candidate 353; stable alone 226. x86_64 only (Asahi reports 330 passed on the M1 for dbd1fbc).
