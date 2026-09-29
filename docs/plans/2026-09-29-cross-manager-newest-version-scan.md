# Cross-manager newest-version scan

Date: 2026-09-29. Status: **shipped** — phases 1-5 complete, verified on CachyOS
and Asahi Linux.

> **Note on divergence from the original plan.** This plan was reviewed by a
> two-model relay chain before implementation, and several decisions below were
> changed as a result. The "Design" section below is preserved as originally
> written so the reasoning stays auditable; the "What actually shipped" section
> at the end is the authoritative record. The three substantive changes were:
> (1) the emit predicate was pinned to "report all installed versions, user
> decides" instead of the undefined "the manager the user currently uses";
> (2) `packaging` is used for semver ecosystems only, never for distro version
> grammars; (3) the curated alias map was cut from v1, then re-added in phase 5
> as a user-managed `SettingsStore` rather than a hardcoded table.

## Goal

Notify the user when an installed package exists on more than one manager and
a *different* manager offers a higher version than the one currently used, and
provide an on-demand action that scans every matching installed package across
all managers and suggests the one with the newest version.

Example: `typescript` installed via pacman at 5.0 while pnpm offers 5.1 —
PolyGet should surface "pnpm has typescript 5.1 (installed: pacman 5.0)" and
let the user act on it.

## Background / constraints found while auditing

- `PackageManager.list_installed()` (`app/core/manager.py:66`) returns names
  only — no versions anywhere in the driver interface. The raw subprocess
  output usually *has* versions (e.g. `npm list -g --json`), but drivers drop
  them (`app/core/drivers/npm.py:179-181`). Versions must be plumbed through
  before any comparison is possible.
- There is no version-comparison dependency (`requirements.txt` has no
  `packaging`; comparison today is display-only semver coloring in
  `app/ui/main_window.py:394-410`). Cross-ecosystem versions are messy
  (pacman `pkgver-pkgrel`, npm semver, cargo semver+metadata).
- Same package name does not always mean the same software across managers
  (npm `typescript` vs pacman `typescript` usually do match; `python-pip`
  vs `pip` do not). Matching must be conservative and ecosystem-aware.
- No system tray exists yet (ROADMAP: future) — "notify" for now means an
  in-app surface (badge/section/dialog) plus CLI output, not OS notifications.
- CLI commands follow the `_gather_per_manager` + `_emit(table|json)` pattern
  (`app/cli.py:175-215`); a new read-only command fits it exactly.

## Design

### 1. Data model — versions alongside installed names

- Add optional base-class method `PackageManager.list_installed_versions()
  -> dict[str, str]` (name → version), defaulting to `{}` so all existing
  drivers keep working untouched.
- Implement it progressively, starting with the JS ecosystem where one scan
  is most valuable: npm, pnpm, yarn (their raw JSON already carries versions;
  pnpm/yarn reuse the `_run` helper added in `97e4906`). Then pipx, cargo,
  gem. System managers (pacman/dnf/apt) last — their version strings need
  `pkgrel`/epoch stripping.
- Name normalization lives in one place: lowercase, strip common prefixes
  (`python-`, `node-`, `perl-`), plus a small explicit alias map in
  `app/core/data/` for known equivalents. Unknown pairs never match.

### 2. Core logic — `app/core/version_scan.py` (new)

- `async def cross_manager_newest(managers) -> list[dict]`: gather
  `list_installed_versions` per available manager (reuse the
  `_gather_per_manager` failure-tolerant shape: per-manager `ok`/`error`, one
  broken manager never sinks the scan).
- Group by normalized name; keep groups present on ≥2 managers.
- Compare with `packaging.version.Version` (add `packaging` to
  `requirements.txt` — de-facto standard, already on any pip system); fall
  back to string equality (no suggestion) when a version doesn't parse, never
  guess an ordering.
- Emit suggestions only when some manager's version is strictly higher than
  the version on the manager the user "currently uses". "Currently used" is
  ambiguous when a package is installed on two managers — report all
  installed versions and mark the highest; let the user decide. Never
  auto-switch managers.
- Result row: `{package, installed: {manager: version}, newest: {manager,
  version}, note}` where `note` covers alias-matched or unparseable cases.

### 3. State wiring / surfaces

- CLI (first, testable without Qt): `run.py newest [--manager M] [--json]` —
  read-only, mirrors `cmd_outdated` output shape (`suggestions` + per-manager
  status). Exit 1 on any manager failure, matching `cmd_outdated`.
- TUI: a "Version check" action next to scan that runs the same core
  function in a worker and renders suggestion rows; reuses the existing
  terminal-log + failure-dialog patterns.
- Qt GUI: a section/badge in the updates view listing cross-manager
  suggestions; clicking a row shows installed-vs-newest per manager. No
  auto-install, no manager switching without explicit user action.
- OS-level notification (tray/toast): explicitly out of scope until the
  ROADMAP tray item lands; the scan core must not depend on it.

### 4. Tests (alongside, per repo guidelines)

- `tests/test_version_scan.py`: mocked drivers — higher-elsewhere detected,
  all-equal silent, unparseable versions produce no suggestion, one failed
  manager doesn't sink the scan, alias map applied, unknown names unmatched.
- Driver tests for each new `list_installed_versions` implementation.
- CLI test for `newest` table + `--json` shapes.

## Phases

1. Base method + `packaging` dep + npm/pnpm/yarn versions + `version_scan.py`
   core + unit tests (no UI).
2. `run.py newest` CLI + test; verify on CachyOS (npm/pacman overlap) and
   Asahi (dnf/npm/pnpm overlap) via real `--json` output.
3. TUI action, then Qt badge/section.
4. Pipx/cargo/gem versions; system-manager versions + alias-map hardening.

## Acceptance

- `run.py newest --json` on a machine with the same package on two managers
  reports the higher one with both installed versions; exit 0.
- No suggestion when versions are equal or unparseable; failed managers
  reported, scan still completes.
- Full suite `QT_QPA_PLATFORM=offscreen pytest` green; no new dependency
  beyond `packaging`.

---

# What actually shipped

All phases complete. 178 tests pass on both machines.

| Phase | Commit | Contents |
|-------|--------|----------|
| 1 | `251270e`, `734e3d1` | `list_installed_versions()` on the base class (defaults `{}`); npm/pnpm/yarn implementations; `app/core/version_scan.py`; `run.py newest` CLI; `packaging>=23.0` dep; 13 unit tests |
| 2 | `1b72957` | TUI `v` binding; Qt "Version Check" nav row + page + badge; `VersionCheckWorker` |
| 3 | `04b5989` | `list_installed_versions()` for pipx, cargo, gem, pacman, dnf, apt |
| 4 | `8455810` | `list_installed_versions()` for dart_pub, poetry, hex, julia, cpanm, flatpak |
| 5 | `dfab51a` | `SettingsStore` (alias map + scan policies); `IgnoreStore` filtering; TUI `VersionCheckModal`; Qt `QTreeWidget` with expandable rows |
| — | `092527b` | App icon, `.desktop` entry, launcher installer (unrelated but shipped alongside) |

All 15 registered drivers now implement `list_installed_versions()`.

## Deviations from the design above, and why

1. **Predicate is "report all installed versions", not "vs. the current
   manager".** The original text specified both, which is contradictory when a
   package is installed on two managers and "currently used" is undefined
   without a settings concept that did not exist. A suggestion row reports every
   installed version and marks the highest; the user decides.

2. **`packaging.version.Version` is used only for semver ecosystems** (NPM, pnpm,
   Yarn). The plan proposed it as a cross-ecosystem comparator, but it is a
   PEP 440 Python-packaging comparator and will silently accept distro grammars
   while producing orderings that are not the ecosystem's. System managers
   (Pacman, DNF, APT) are compared component-wise after epoch/pkgrel stripping.
   This is why the plan's "strip the Debian epoch" instruction was kept only as
   a *normalization* step, never as a comparison against PEP 440.

3. **The alias map was cut, then re-added differently.** The plan's curated
   table in `app/core/data/` had no user control, no storage backend, and would
   have applied one global mapping across all ecosystem pairs. It shipped as a
   user-managed `SettingsStore` (`~/.config/polyget/settings.json`) instead, and
   a suggestion derived from an alias is tagged `note: "alias-matched"` so a
   consumer can filter it.

4. **`IgnoreStore` integration is "ignored when *all* installed versions are
   ignored per-manager."** The store is keyed on `(manager, package)`, so a
   cross-manager suggestion cannot be ignored as a single unit. The current rule
   is the conservative one: an ignored package must be ignored on every manager
   it appears on to drop out of the scan.

5. **No caching of the scan.** The review flagged that a second full sweep of
   every manager duplicates work the GUI's update scan already does. That remains
   unaddressed — `check_updates` returns `{"name", "current", "new"}` and
   `search_packages` already returns a `version` field, so a future revision
   could reuse either instead of calling `list_installed_versions()`.

## Known limitations

- **Distro-repack vs. upstream version advice is unsound.** A distro package at
  a lower `pkgver` is not necessarily older, because distros backport fixes
  without moving the upstream version. Worse, distros and language runtimes
  sometimes number the *same* release independently: Arch ships
  `ruby-google-protobuf 36.1-1.1` while the Ruby gem is `4.36.1`, so a numeric
  comparison reports a "newer" version that is not one. Handled by the untrusted
  pair table below plus a `note: "cross-ecosystem-unverified"` caveat on
  distro-vs-runtime results. The `check_vulnerabilities()` suppression guard
  proposed in review was **not** implemented and remains the highest-value
  remaining item.
- **Trust is per manager-pair, and partly empirical.** The RubyGems-vs-distro
  rule is derived from this host's 65 observed overlaps (exactly one of which
  showed a version difference, and it was the false positive). The principled
  part is that `Gem::Version` and distro `pkgver` are independent counters. If a
  later machine shows a legitimate gem-vs-distro finding, this should become
  per-package rather than per-manager. Users can suppress a bad pair without a
  code change via `version_scan.untrusted_pairs` in settings.
- **Same-registry managers are flagged but not separated.** npm, pnpm, and yarn
  all reach the npm registry, so a package installed under two of them at
  different versions is really a shadowed-global-prefix problem, not a newer
  version elsewhere. Such rows are tagged `note: "same-registry"`.
- **The desktop entry hardcodes the repo path** and goes stale if the repo
  moves; re-run `scripts/install-desktop.sh`.

---

# Correction: the comparator was not actually functional

An audit of live scan data on both hosts (2026-09-29, after the commits above)
found the feature **was not firing at all**, and had never been exercised
outside unit tests. CachyOS has 81 genuine cross-manager overlaps out of 2182
package names and reported **zero** suggestions.

Root cause: `_version_greater` dispatched on a hardcoded manager whitelist
(`_JS_MANAGERS` | `_SYSTEM_MANAGERS` = 6 managers) and returned `None` for
everything else. Nine drivers that report versions — Pipx, Cargo, RubyGems,
Dart Pub, Poetry, Hex, Julia, cpanm, Flatpak — fed their data in and got
nothing back. Phases 3 and 4 added `list_installed_versions()` to those drivers
but never gave them a comparator, so the data was collected and discarded.

A concrete false negative from the live probe:

```
uvicorn: {'Pacman': '0.52.4-1', 'Pipx': '0.53.0'} -> best=None  [dropped]
```

## What changed (`cc3f9d8`)

- **Generic runtime comparator.** Every non-distro ecosystem now routes through
  `_parse_semver`, which tolerates Cargo's `v4.2.0` prefix, drops semver build
  metadata (`1.0.0+build` == `1.0.0`), and orders prereleases below releases for
  both semver (`1.0.0-rc.1`) and PEP 440 (`1.0.0rc1`) spellings. Comparison is
  numeric, not lexicographic (`2.0 < 10.0`).
- **Ecosystem pairing (`_comparators`).** Two managers are only comparable if
  they share a version scheme: same runtime ecosystem (NPM/pnpm/Yarn,
  Pipx/Poetry, …), or a distro manager against a runtime manager (the system
  copy of a package the runtime also ships). Two *different* runtimes are
  refused — a gem named `yaml` and a PyPI package named `yaml` are unrelated
  software. Flatpak is never compared to anything; its versions are packager
  app versions, not upstream releases.
- **Incomparable versions dropped before grouping.** RubyGems reports
  interpreter-bundled gems as `default: 0.4.0`; those track the Ruby stdlib, are
  not separately installable, and are now excluded by `_is_comparable_version`
  rather than being carried into a comparison where they could win.
- **Regression tests from live data.** 12 new tests, each named for the real
  overlap that produced it (`test_uvicorn_regression_pipx_beats_distro`,
  `test_ruby_stdlib_gem_never_suggested_against_distro`,
  `test_cross_ecosystem_suggestion_is_flagged`, …). Suite is 190 tests.

Live result after the fix, on CachyOS:

```
PACKAGE          NEWEST_MANAGER  NEWEST_VERSION  INSTALLED
google-protobuf  Pacman          36.1-1.1        RubyGems=4.36.1, Pacman=36.1-1.1
uvicorn          Pipx            0.53.0          Pacman=0.52.4-1, Pipx=0.53.0
```

`uvicorn` is a true positive that was previously dropped. `google-protobuf` is
the false positive described above, now flagged in the output rather than
presented as fact.

## Per-pair trust (`_UNTRUSTED_PAIRS`)

The first fix suppressed the false positive by disabling *all* distro-vs-runtime
comparisons, which also discarded the one genuine finding — leaving the feature
inert on both hosts. Measuring the overlap population showed why that trade was
bad:

| Pair | Overlaps | With a version difference |
|------|----------|---------------------------|
| RubyGems ↔ Pacman | 65 | 1 (and it was the false positive) |
| NPM ↔ Pacman | 4 | 0 |
| Pacman ↔ Pipx | 2 | 1 (and it was the true positive) |

The real discriminator is not "is this finding true?" but **do both sides count
the same release the same way?** So trust is now decided per *pair of managers*:

- **Trusted** — same runtime ecosystem, or a distro manager against a runtime
  manager whose projects track upstream versioning (Pipx/Poetry ↔ distro). This
  keeps `uvicorn 0.53.0` vs `0.52.4-1` reportable.
- **Untrusted** — RubyGems ↔ any distro (`Gem::Version` and `pkgver` are
  independent counters, which is what produced the `google-protobuf` false
  positive) and npm/pnpm/yarn vs each other (same registry, so a version gap
  means a shadowed global install, not a newer release).

Unlisted pairs are trusted, because a false negative is recoverable while a
confident wrong "newer version is available" is not. Users can suppress any
pair they hit in the wild via `version_scan.untrusted_pairs` in settings
(`[["Pipx", "Pacman"]]`), which needs no code change.

Live result after both fixes, on CachyOS:

```
PACKAGE  NEWEST_MANAGER  NEWEST_VERSION  INSTALLED
uvicorn  Pipx            0.53.0          Pacman=0.52.4-1, Pipx=0.53.0
! uvicorn: Pipx 0.53.0 vs Pacman 0.52.4-1 — these managers number the same
  release independently, so this is a lead, not a confirmed upgrade.
```

One true positive surfaced, zero known false positives. The caveat text is
conservative — it fires for trusted pairs too, because a trusted pair is a
judgment about *this* host's observed data, not a guarantee for every project.
