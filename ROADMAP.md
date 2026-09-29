# ❖ Roadmap

Tracks planned work for PolyGet. Full design/implementation detail for everything below lives in
`docs/plans/2026-07-16-polyget-features-and-improvements.md` — this file is the checklist view;
that file is the *why* and *how*.

## Recently shipped

- [x] Cross-manager newest-version scan — `list_installed_versions()` on all 15 drivers, `run.py newest`, TUI `v` binding, Qt Version Check page, ecosystem-aware comparators, per-manager-pair trust gating (`cc3f9d8`, `2a14c38`)
- [x] Fix npm update-loop (semver `wanted` vs `latest` mismatch) and Qt UI stall on bare `sudo` (`30a12f0`)
- [x] Surface batch-upgrade failures instead of always reporting success (`6b831c0`)
- [x] `apt` driver — Debian/Ubuntu System-category coverage, matching the existing DNF/Pacman drivers
- [x] Pending-updates count badge on the sidebar's "System Updates" row
- [x] App icon, `.desktop` entry and launcher installer (`092527b`)

## New features

- [ ] Package pin/ignore list — persist per-package exclusions so outdated packages don't get force-selected on every scan
- [ ] Optional vulnerability scanning — detect `pacman-audit`/`pip-audit`/`osv-scanner`/`cargo-audit` and surface advisories, gated on a scanner actually being present. See the "rejected" note below for why this is a scanner-availability feature, not a version-comparison guard.
- [ ] Update history log — append-only record of what got upgraded, when, and whether it succeeded
- [ ] System tray + background scan — periodic scan with a tray badge, no need to keep the window open

## Improvements

- [ ] **Distinguish an empty result from a failed one across the driver interface** — `list_installed()` returns `[]` and `check_vulnerabilities()` returns `[]` both for "genuinely nothing" and for "the subprocess failed / the scanner isn't installed". These collapse silently, so callers cannot tell a clean system from a broken driver. This blocks the vulnerability-scanning feature above and is the prerequisite for any correct use of `check_vulnerabilities()`. Applies to `list_installed()`, `list_installed_versions()`, and `check_vulnerabilities()` across all drivers.
- [ ] Retry action on the batch-upgrade failure dialog, instead of requiring a full reselect
- [ ] Audit `handle_sync_worker_finished` / `handle_blueprint_sync_worker_finished` for the same silent-success pattern just fixed in the main upgrade queue
- [ ] Parallelize independent (non-elevated) managers in the batch-upgrade queue
- [ ] Split `self.upgrade_queue`'s overloaded tuple shape into three correctly-typed queues (upgrade / sync / blueprint-install)
- [ ] Per-package changelog/release notes before upgrading, especially for major-version bumps
- [ ] Semver-aware coloring (major/minor/patch) in the updates list
- [ ] Verify npm's `search_packages` still gets results from the deprecated `npm search` registry endpoint
- [ ] Dry-run mode — show the exact command PolyGet would run without executing it
- [ ] Persist window state / last-selected nav tab between runs

## Rejected / not doing

- ~~Suppress cross-manager version suggestions when the installed copy is not vulnerable.~~ Rejected
  2026-09-29 after checking prerequisites. Intended as a guard on the cross-manager
  version scan: only suggest "a newer version exists" when the currently-installed
  copy is actually vulnerable, since distros backport fixes without moving the
  upstream version. The guard cannot work as designed:

  - Only 2 of 15 drivers implement `check_vulnerabilities()` (npm, Cargo).
  - On the CachyOS host every relevant manager returns `0` advisories, because
    `pacman-audit`, `pip-audit`, `trivy`/`grype`/`osv-scanner` and
    `rpm %{_queryadvisory}` are all absent. "No scanner installed" is
    indistinguishable from "no vulnerabilities".
  - Acting on that confusion inverts the failure: for the one genuine finding
    (uvicorn 0.53.0 via pipx vs 0.52.4-1 via pacman) the guard would read
    "not vulnerable" and suppress a true positive, because nothing was scanning.
  - npm is the one manager with working audit data (it ships with npm and returns
    real version ranges), but npm is now an untrusted same-registry pair and
    cannot produce a cross-manager finding to guard.

  Replaced by the empty-vs-error contract fix above, which is the real
  prerequisite, and by the `cross-ecosystem-unverified` caveat, which tells the
  user to judge the lead themselves. Revisit only once scanners are detectable.

---

Have an idea that's not here? Open an issue, or add it straight to this file with a short rationale.
