# ❖ Roadmap

Tracks planned work for PolyGet. Full design/implementation detail for everything below lives in
`docs/plans/2026-07-16-polyget-features-and-improvements.md` — this file is the checklist view;
that file is the *why* and *how*.

## Recently shipped

- [x] Fix npm update-loop (semver `wanted` vs `latest` mismatch) and Qt UI stall on bare `sudo` (`30a12f0`)
- [x] Surface batch-upgrade failures instead of always reporting success (`6b831c0`)
- [x] `apt` driver — Debian/Ubuntu System-category coverage, matching the existing DNF/Pacman drivers

## New features

- [ ] Package pin/ignore list — persist per-package exclusions so outdated packages don't get force-selected on every scan
- [ ] Security audit surface — surface `npm audit`/`cargo audit`/`pip-audit`-style vulnerability data, not just "outdated"
- [ ] Update history log — append-only record of what got upgraded, when, and whether it succeeded
- [ ] System tray + background scan — periodic scan with a tray badge, no need to keep the window open

## Improvements

- [ ] Retry action on the batch-upgrade failure dialog, instead of requiring a full reselect
- [ ] Audit `handle_sync_worker_finished` / `handle_blueprint_sync_worker_finished` for the same silent-success pattern just fixed in the main upgrade queue
- [ ] Parallelize independent (non-elevated) managers in the batch-upgrade queue
- [ ] Distinguish real "0 installed" from a caught exception in `list_installed()` across drivers
- [ ] Split `self.upgrade_queue`'s overloaded tuple shape into three correctly-typed queues (upgrade / sync / blueprint-install)
- [ ] Per-package changelog/release notes before upgrading, especially for major-version bumps
- [ ] Semver-aware coloring (major/minor/patch) in the updates list
- [ ] Verify npm's `search_packages` still gets results from the deprecated `npm search` registry endpoint
- [ ] Dry-run mode — show the exact command PolyGet would run without executing it
- [ ] Persist window state / last-selected nav tab between runs

---

Have an idea that's not here? Open an issue, or add it straight to this file with a short rationale.
