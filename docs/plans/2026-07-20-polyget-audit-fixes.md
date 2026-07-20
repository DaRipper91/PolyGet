# PolyGet: Silent-failure and privilege-escalation fixes from the 2026-07-20 audit

> **Implement task-by-task, in order.** Start with **Task 1 (missing subprocess timeouts in DNF/
> pnpm/Yarn)** — this is the one finding that can permanently deadlock the app's core "Check for
> Updates" flow with zero error message, on drivers (DNF, pnpm) that are confirmed actually
> installed and live on this project's own Fedora/Asahi daily-driver machine.

**Context:** PolyGet is a PySide6 (+ Textual TUI) desktop app that unifies package management
across 15 driven backends (DNF, Pacman, APT, Flatpak, NPM, Cargo, Pipx, RubyGems, etc.) plus 15
catalog-only/browsable managers. This pass audited the current HEAD plus a large uncommitted
working-tree diff (17 files) that itself implements two items from an earlier plan doc (silent
sync/blueprint failure surfacing, upgrade-queue refactor) and re-verified all three of CLAUDE.md's
previously-documented "known bugs." The driver-registry pattern, `SubprocessCoordinator`'s
process-group cleanup, `BlueprintManager`'s strict-reject YAML parsing, the Flatpak OCI
ghost-update filter, and the Julia driver's argument-passing injection fix are all confirmed solid
this pass (live-tested where possible) — none of these need touching; see "Already solid" note at
the end of this doc before changing any of them.

---

## Task 1 — Add subprocess timeouts to DNF/pnpm/Yarn (and other list_installed()s) that lack them

**Problem:** Every driver except the ones below wraps `proc.communicate()` in
`asyncio.wait_for(..., timeout=N)`. These do not:
- `app/core/drivers/dnf.py:35` and `:64` (both `check_updates()` subprocess calls) and `:110`
  (`list_installed()`)
- `app/core/drivers/pnpm.py:23` (`check_updates()`) and `:42` (`list_installed()`)
- `app/core/drivers/yarn.py:23` (`check_updates()`) and `:50` (`list_installed()`)
- `app/core/drivers/flatpak.py:152` (`list_installed()` only — its `check_updates()` is correctly
  timeout-wrapped)
- `app/core/drivers/cpanm.py:24`, `dart_pub.py:23`, `hex.py:23`, `poetry.py:30`
  (`list_installed()` only; their `check_updates()` are static `[]` stubs with no subprocess call)

`ScanWorker.run()` (`app/ui/main_window.py:81-99`) drives every manager's `check_updates()` through
a single `asyncio.gather(*tasks)`, and `FetchInstalledWorker.run()` (`main_window.py:321-345`) does
the same for `list_installed()`. A single hung subprocess (DNF stalling on an unreachable mirror,
or pnpm/yarn stalling on a dead registry) blocks that `gather()` forever, so `finished_all`/
`result_signal` never fires. Because `scan_all()` sets `self.scan_in_progress = True` and disables
`btn_scan` *before* starting the worker (`main_window.py:1569-1572`) and only clears it in
`handle_scan_finished()` — reachable only via `finished_all` — a single hung DNF/pnpm/yarn call
permanently disables "Check for Updates" for the app's remaining lifetime with no error shown. The
same applies to "Export Local Configuration"/"Sync System to Blueprint" via `FetchInstalledWorker`.
No existing test catches this (every test mocks `proc.communicate()` with an instantly-resolving
`AsyncMock`). This is verified-by-code-tracing (deterministic, not a live reproduction) — the
absence of `wait_for` is grep-confirmed fact, the downstream "button stays disabled forever" is a
logic trace, not an observed hang.

**Steps:**
1. Wrap `dnf.py:35`, `:64`, `:110`; `pnpm.py:23`, `:42`; `yarn.py:23`, `:50`; `flatpak.py:152`;
   and `cpanm.py:24`, `dart_pub.py:23`, `hex.py:23`, `poetry.py:30` in `asyncio.wait_for(...,
   timeout=N)`, matching the timeout convention already used by sibling drivers (e.g. apt.py's
   15s/10s/12s split by call type).
2. On `asyncio.TimeoutError`, raise the same `RuntimeError(...)` pattern the other 10 drivers'
   `check_updates()` already use, so it routes through the existing `error_signal`/`scan_errors`
   surfacing path rather than hanging `asyncio.gather()`.
3. Add or extend a test per fixed driver asserting a timeout raises rather than hangs (mock
   `asyncio.wait_for` to raise `TimeoutError` and assert the driver surfaces it, not swallow it).
4. Confirm `ScanWorker`/`FetchInstalledWorker` still complete and clear their in-progress flags when
   one manager's call raises instead of hanging.

---

## Task 2 — Fix Pipx's silently-swallowed per-package update-check failures (this is the actual CLAUDE.md "fake PyPI lookup" bug)

**Problem:** `app/core/drivers/pipx.py:24-58`, specifically the bare `except Exception: pass` at
lines 56-57, which falls through to `return []`. `check_updates()` (`pipx.py:60-94`) gathers these
per-package results via `asyncio.gather(*tasks)` and never sees an exception from
`_check_package()`, so the `raise RuntimeError(...)` this repo's uncommitted diff added at
`pipx.py:93-94` can only ever fire for a failure in the initial `pipx list --short` call — never
for a failure in the actual per-package `pip list --outdated` check (corrupted JSON, permissions
issue, broken venv, etc.). That per-package failure path is exactly the "reports success without
actually checking" behavior CLAUDE.md describes. Note for whoever picks this up: an earlier stage
of this same audit initially concluded the network I/O in `check_updates()`/`_check_package()` was
real (true, and still true) and recommended CLAUDE.md's bug description be re-scoped — that
recommendation is superseded by this finding. The bug is real, just one call-frame deeper than
first thought: `_check_package`'s exception handling, not the overall network path.

**Steps:**
1. In `_check_package()` (`pipx.py:24-58`), replace the bare `except Exception: pass` /
   `return []` fallthrough with either a re-raise or a per-package error marker (e.g. a dict with an
   `error` key) that `check_updates()` can distinguish from a genuine "no update available" result.
2. Update `check_updates()` (`pipx.py:60-94`) to surface any per-package failures — either by
   raising `RuntimeError` (consistent with the rest of the diff's error-surfacing pattern) or by
   aggregating them into the return value in a way `ScanWorker` can report per-manager.
3. Add a test that makes one package's `pip list --outdated` call raise/return malformed JSON and
   asserts `check_updates()` does *not* silently report that package as up to date.
4. Leave `search_packages()`'s weekly-cached substring-match staleness (`pipx.py:202-215`) alone —
   confirmed a separate, lower-severity limitation, not part of this bug.

---

## Task 3 — Migrate Arch-family catalog self-install commands from `sudo` to `pkexec`

**Problem:** `[reasoned from code — not verified by direct execution on Arch hardware in this audit
session]` 21 of `app/core/data/manager_catalog.yaml`'s `arch:` self-install entries use the literal
pattern `["sudo", "pacman", "-S", "--noconfirm", ...]` (e.g. lines 26, 37, 50, 62, 74, 142, 180,
192, ...), while every `fedora:`/`debian:`/`suse:` entry for the same managers correctly uses
`["pkexec", ...]` (42 pkexec entries vs. 21 sudo entries — the split is exactly "arch family" vs.
everything else). `docs/plans/2026-07-08-polyget-enhancements-and-features.md` documents an
explicit, deliberate migration of DNF's privileged commands from `sudo` to `pkexec`, including
removing sudo stdin writes of a hardcoded password from `ExecutionWorker` — and indeed,
`ExecutionWorker.run()` (`app/ui/main_window.py:132-163`) never opens or writes to `proc.stdin` at
all today. That migration was never applied to the catalog's Arch-family self-install commands.
Every "Install" click on the Package Managers page
(`ManagerItemWidget` → `install_manager_backend()`, `main_window.py:1507-1521`) for a
not-yet-installed manager on an Arch-family system — one of only two real hardware targets this
project develops against — invokes plain `sudo` with no TTY and no stdin password channel. The code
facts here (21 raw-`sudo` catalog entries, no `proc.stdin` channel in `ExecutionWorker`) are
grep/read-confirmed solid; the specific "will fail immediately or hang" behavioral claim was
reasoned from `sudo`'s documented non-interactive behavior, not reproduced on this audit's
Fedora/Asahi-only test machine.

**Steps:**
1. Change all 21 Arch-family self-install entries in `manager_catalog.yaml` from `["sudo", ...]` to
   `["pkexec", ...]`, matching the pattern already used by every other distro family's entries.
2. Verify no other Arch-specific command elsewhere in the catalog or drivers still assumes a raw
   `sudo` invocation with stdin input.
3. Once on Arch hardware (CachyOS), manually verify a catalog-only manager install (e.g. `paru`)
   now prompts via the polkit agent rather than failing/hanging silently.
4. Add/update a catalog-loading test asserting no `arch:` self-install command list begins with the
   literal string `"sudo"`.

---

## Task 4 — Remove or repair the TUI's dead sudo-password-retry fallback

**Problem:** `app/ui/tui.py:380`: `is_sudo = cmd[0] == "sudo"`. A repo-wide grep confirms no
driver's `get_upgrade_command()` returns `"sudo"` as the first argument anymore — DNF, Pacman, and
APT all correctly return `["pkexec", ...]`, and NPM's privilege-escalation fallback was migrated to
`["pkexec"] + base_cmd` in commit `30a12f0`. `is_sudo` is therefore always `False` today, so the
retry-with-password branch at `tui.py:425-437` (which pushes `PasswordModal` and retries with a
user-typed password) can never execute. This matters specifically for a *terminal* UI: if `pkexec`
fails because no polkit authentication agent is bound to the session (a normal condition over SSH
or in a minimal/no-DE terminal — exactly the use case a TUI exists for), the TUI has no fallback
path to let the user authenticate at all; it just reports the upgrade as failed with no retry
option, silently defeating `PasswordModal`'s design intent. This is a regression left over from the
pkexec migration, not a newly-introduced bug, but is unaddressed by the current diff.

**Steps:**
1. Decide the intended behavior: either (a) restore a real fallback path — detect a `pkexec`
   failure specifically (e.g. no auth agent) and offer the `PasswordModal`/`sudo`-with-typed-password
   retry in that case, or (b) remove `PasswordModal`/the dead `is_sudo` branch entirely if pkexec-only
   is now the intended design for the TUI.
2. If (a): update `_upgrade_manager` (`tui.py:361-442`) to detect the specific pkexec
   no-auth-agent failure mode (not just any nonzero exit) before falling back to the sudo-password
   retry, so it doesn't mask other real pkexec failures as "needs a password."
2. If (b): remove `PasswordModal` and the dead branch, and note in the TUI's docs/help text that
   authentication requires a bound polkit agent.
3. Add a test exercising whichever path is chosen (a mocked pkexec failure that either triggers the
   restored fallback, or confirms the simplified failure-reporting behavior).

---

## Task 5 — Add deb822 `.sources` parsing support to apt.py's `list_repos()`

**Problem:** `[reasoned from code + documented upstream Ubuntu/Debian behavior — not reproduced
against a live Debian/Ubuntu system in this audit session]` `list_repos()` (`apt.py:105-127`) only
globs `*.list` files and never parses the deb822 `.sources` format: `apt.py:114`,
`sources = ["/etc/apt/sources.list"] + glob.glob("/etc/apt/sources.list.d/*.list")`. Since Ubuntu
24.04 ("Noble"), the default repository configuration ships as
`/etc/apt/sources.list.d/ubuntu.sources` in deb822 (`Types:`/`URIs:`/`Suites:`/`Enabled:` stanza)
format — a `.sources` extension, not `.list` — and `/etc/apt/sources.list` itself ships
empty/commented-out on these systems. Debian 12 ("Bookworm") and later similarly default new
entries to `.sources`. Because the glob only matches `*.list`, and the legacy
`line.startswith("deb ")`/`"# deb"` parser (lines 120-123) wouldn't parse deb822 stanza syntax even
if a `.sources` file were included, `list_repos()` returns `[]` (or only whatever legacy `.list`
fragments happen to coexist) on modern Ubuntu/Debian even though repos are genuinely configured and
active. Neither `test_apt_list_repos_parses_sources_list` nor
`test_apt_list_repos_handles_missing_files` (`tests/test_apt_driver.py:164, 187`) exercises a
`.sources`-format fixture. The underlying technical claim (Ubuntu 24.04+ defaults to deb822) is
solid, well-documented public knowledge — the specific "breaks the Repositories page" consequence
was reasoned from code, not reproduced against a live Debian/Ubuntu box in this audit session.

**Steps:**
1. Extend `list_repos()`'s glob to also match `*.sources` files under
   `/etc/apt/sources.list.d/`.
2. Add a deb822-stanza parser (blank-line-delimited `Key: Value` blocks reading `Types`, `URIs`,
   `Suites`, `Components`, `Enabled`) alongside the existing legacy one-line parser, producing the
   same `{"id", "name", "url", "enabled"}` dict shape the rest of the codebase expects.
3. Add a fixture-based test using a realistic `ubuntu.sources`-style deb822 file and assert it's
   parsed into the expected repo dicts, including an `Enabled: no` case mapping to
   `enabled: False`.
4. If possible, validate against a real Ubuntu 24.04+ or Debian 12+ system (or this project's cloud
   sandbox, which CLAUDE.md notes runs on a fixed Ubuntu base) before considering this closed.

---

## Task 6 — Add generation/staleness guards to Search, Category, and Repo-fetch workers

**Problem:** `scan_all()` (`main_window.py:1564-1612`) stamps every scan with
`self.scan_generation`, and `handle_scan_results`/`handle_scan_error` (`main_window.py:1614-1657`)
discard results whose generation doesn't match the current one — but the identical
stale-result-overwrite risk exists, unguarded, elsewhere:
- `perform_store_search()` (`main_window.py:1813-1845`) and `on_category_changed()`
  (`main_window.py:1785-1811`) both start a new `SearchWorker`/`CategoryWorker` and connect its
  `results_signal` to the same `handle_store_results()` with no cancellation or generation check
  against any prior still-running worker — a slow, now-stale search can silently overwrite a
  faster, newer one if the user searches twice quickly.
- `load_repos_for_selected_manager()` (`main_window.py:1409-1420`) has the same shape: switching
  manager rows on the Repositories page fast enough can let an earlier (slower) manager's
  `FetchReposWorker` result land after a later (faster) one, via `display_repos_list(repos, mgr)`
  (`main_window.py:1422-1431`) unconditionally repopulating the widget — potentially displaying,
  e.g., Flatpak's remotes mislabeled under a currently-selected DNF row with no indication anything
  is wrong.

**Steps:**
1. Add the same generation-stamp pattern used by `scan_all()`/`handle_scan_results` to
   `perform_store_search()`/`on_category_changed()`/`handle_store_results()` — stamp each
   `SearchWorker`/`CategoryWorker` launch and discard results whose generation is stale.
2. Apply the same pattern to `load_repos_for_selected_manager()`/`display_repos_list()`, keyed on
   both a generation counter and the target manager, so a late-arriving result for a
   no-longer-selected manager is dropped.
3. Add regression tests: fire two searches/category-changes/repo-loads in quick succession with the
   first mocked to resolve after the second, and assert the UI reflects the second (newer) result,
   not the first.

---

## Task 7 — Add duplicate-launch guards to manager-install, store-install, and repo-action buttons

**Problem:** This diff's `self.active_operation`/`self.scan_in_progress` mutual-exclusion guards
were added specifically to `scan_all()`, `start_batch_upgrade()`, `sync_repositories()`,
`export_local_configuration()`, and `sync_system_to_blueprint()` — but the same
unguarded-duplicate-launch pattern still exists, untouched, in:
- `install_manager_backend()` (`main_window.py:1507-1521`) — the "Install" button in
  `ManagerItemWidget` is never disabled, so a second click before the first `pkexec dnf install...`
  finishes spawns a second, concurrent, identical privileged install command.
- `install_package()` (`main_window.py:1884-1921`) — same pattern for Store search-result installs.
- `add_repository_source()` / `toggle_repository_source()` / `remove_repository_source()`
  (`main_window.py:1433-1483`) — same pattern for repo add/enable/disable/remove actions.

None of these are new regressions — they're the same bug class this diff already fixed for the
scan/upgrade/sync/blueprint flows, just not yet extended to these three flows, which is worth
closing given that closing exactly this gap was the diff's own stated intent.

**Steps:**
1. Extend the existing `active_operation`-style guard (or a lighter per-widget "in flight" flag) to
   `install_manager_backend()`, `install_package()`, and the three repo-action methods.
2. Disable the triggering button/row while its operation is in flight, re-enabling on completion or
   error, consistent with how `btn_scan` is handled for `scan_all()`.
3. Add a test covering at least one of these three flows: trigger the action twice quickly and
   assert only one subprocess launch occurs.
4. Add a regression test for the newer `self.active_operation` guard itself (added by this diff to
   the scan/upgrade/sync/blueprint flows) — confirmed to currently have no direct test coverage
   (`grep -n "active_operation" tests/test_blueprint_gui.py` → no hits).

---

## Task 8 — Make Pipx's PyPI index-cache write atomic and race-safe

**Problem:** `app/core/drivers/pipx.py:146-175`, `_ensure_index_cached()` checks the cache file's
mtime and, if stale, downloads and calls `self._INDEX_CACHE_PATH.write_text(json.dumps(names),
...)` directly (`pipx.py:171`) with no locking or atomic write-then-rename. Two concurrent
`PipxManager.search_packages()` calls (e.g. two overlapping `SearchWorker` runs, per Task 6's
finding) racing past the staleness check at the same time will both download and both call
`write_text()` on the same path, risking a truncated/corrupted JSON cache file if the writes
interleave.

**Steps:**
1. Write the refreshed index to a temp file in the same directory, then `os.replace()`/rename it
   over the real cache path (atomic on the same filesystem).
2. Optionally add a simple file lock (or an in-process `asyncio.Lock` guarding
   `_ensure_index_cached()`) to avoid redundant concurrent downloads, not just corrupted writes.
3. Add a test simulating two concurrent `_ensure_index_cached()` calls and asserting the cache file
   is always valid JSON afterward.

---

## Task 9 — Fix apt.py's `#deb` (no-space) disabled-repo detection gap

**Problem:** `apt.py:121`: `if not enabled and not line.startswith("# deb"): continue`. This only
recognizes `# deb ` (literal space after `#`) as a commented-out entry — `#deb-src http://...` (a
common shorthand with no space, syntactically valid in a sources.list) is silently dropped from the
results entirely instead of being surfaced as a disabled repo. This is a minor under-reporting gap,
additive to Task 5's `.sources`-format gap but distinct from it.

**Steps:**
1. Normalize the line (strip the leading `#` and any following whitespace) before checking for the
   `deb`/`deb-src` prefix, so both `# deb ...` and `#deb ...` are recognized as disabled entries.
2. Add a test fixture with a no-space `#deb-src` line and assert it appears in `list_repos()`'s
   output with `enabled: False` rather than being dropped.

---

## Task 10 — Normalize apt.py's multiarch package-name handling between check_updates() and list_installed()

**Problem:** `check_updates()` derives `name` via `line.split("/", 1)[0]` (`apt.py:46`) against
`apt list --upgradable` lines, which for multiarch-enabled packages look like
`libc6:amd64/jammy-updates ...` — the `:amd64` qualifier is retained in the returned `name`.
`list_installed()` (`apt.py:88`), by contrast, returns whatever `apt-mark showmanual` prints, which
is normally the bare package name without an arch qualifier. The two methods are never
cross-matched by name elsewhere in the codebase today, so this isn't causing a live functional
mismatch, but it's a real naming inconsistency between apt.py's own methods that shows up as a
cosmetic `libc6:amd64` entry in the Updates list (inconsistent with every other package's plain
name), and would become a real matching bug if a future feature cross-references these results by
exact string equality.

**Steps:**
1. Decide the canonical name format (with or without the arch qualifier) and apply it consistently
   in both `check_updates()` and `list_installed()`.
2. If the qualifier is stripped from `check_updates()`, keep the arch info available separately if
   it's ever needed (e.g. as a second dict key) rather than discarding it outright.
3. Add a test with a `libc6:amd64/...` fixture line asserting the returned name matches whatever
   convention `list_installed()` uses for the same package.

---

## Task 11 — Pin a tested version range in requirements.txt

**Problem:** `requirements.txt:1-4` pins only lower bounds (`PySide6>=6.5.0`, `textual>=0.50.0`,
`rich>=13.0.0`, `PyYAML>=6.0.0`) with no upper bound. `textual>=0.50.0` spans an enormous range —
this audit's live run used `textual==8.2.7`, and Textual's API has changed meaningfully across that
range (screen/worker/binding APIs). Nothing is broken today (116/116 tests pass against the
currently-installed versions), so this isn't a confirmed live bug, but a fresh install resolving an
older 0.5x-series `textual` satisfying the same `>=` constraint has no guarantee of behaving the
same way the code was actually validated against.

**Steps:**
1. Add explicit upper bounds (or exact pins) reflecting the versions this codebase is actually
   tested against (PySide6 6.11.x, textual 8.x, rich 13.x+, PyYAML 6.x).
2. Document the tested version set somewhere discoverable (README or AGENTS.md) if not pinning
   exactly.

---

## Task 12 — Correct CLAUDE.md's "known bugs" section to reflect current findings

**Problem:** All three of CLAUDE.md's documented "known, previously-confirmed bugs" needed
correction this pass:
- **Flatpak `-j` flag**: not reproducible against current code (`flatpak.py` uses `--json`
  throughout, no `-j` literal anywhere in `app/`) or against this machine's real `flatpak 1.18.0`
  binary (both `flatpak remote-ls --updates -j` and `flatpak list -j` return valid JSON with exit
  code 0). Either already fixed before tracked history begins, or refers to a flatpak-CLI
  version/quirk not present on 1.18.0.
- **Pipx "fake PyPI lookup"**: does not match `check_updates()`/`_check_package()`'s actual network
  I/O at any point in tracked history (confirmed back to the initial commit `86614a4`) — but *is*
  real, just one call-frame deeper, in `_check_package`'s silently-swallowed exceptions (see Task 2
  above). The description should point at that specific code path, not the overall network check.
- **Pacman inverted exit-code**: the documented case (`pacman -Qu` returning 1 on "no updates") is
  correctly handled and test-covered in `check_updates()` (`pacman.py:19-41`,
  `test_pacman_check_updates_no_updates`). The upgrade-command path
  (`get_upgrade_command()` → `pkexec pacman -Syu --noconfirm`, executed generically by
  `ExecutionWorker`) has no equivalent special-casing and was reasoned-but-not-executed to be safe
  since `-Syu` doesn't share `-Qu`'s convention — this remains unverified by direct execution
  (pacman isn't installed on this audit's Fedora/Asahi machine).

**Steps:**
1. Update CLAUDE.md's "Known, previously-confirmed bugs" section: mark the Flatpak `-j` item as
   not-currently-reproducible (or remove it, if a maintainer confirms it's fully stale), re-point
   the Pipx bug description at `_check_package`'s exception handling specifically (linking to Task 2
   above once fixed), and add a note that Pacman's `check_updates()` path is confirmed safe while
   the `-Syu` upgrade-command path remains unverified pending a real Arch-machine check.
2. Cross-reference this update against whichever of Tasks 2/3 are completed, so CLAUDE.md doesn't
   end up describing a bug that's already fixed by the time someone reads it.

---

## Task 13 — Clean up stale docs, stray files, and dev-onboarding gaps

**Problem:** Several small, non-functional issues accumulated:
- `RIP_IT_APART_FIXPLAN_2026-07-12.md` is still sitting at repo root (not moved into `docs/plans/`,
  not removed) despite its 3 items already being shipped in commits `30a12f0`/`59e0596`.
- `run.py:2`'s docstring reads "Launcher script for the Ultimate Package Upgrader GUI" — a leftover
  pre-rebrand name; the app is PolyGet everywhere else (window title, `app.setApplicationName
  ("PolyGet")` in `app/main.py:21`, README, CLAUDE.md).
- `CLAUDE.md:42` states `app/core/` is "adapted from upgrader-tui" — no `upgrader-tui`
  project/module reference exists anywhere else in the repo; likely stale.
- `app/core/coordinator.py:50-51`'s comment still says "Since `preexec_fn=os.setsid` is used, the
  spawned process has a process group ID equal to its PID" — the mechanism is now
  `start_new_session=True` (the effect is identical, so `os.killpg()` still works correctly, but the
  comment names the wrong mechanism).
- `ROADMAP.md`'s "Improvements" checklist still lists "Audit `handle_sync_worker_finished` /
  `handle_blueprint_sync_worker_finished` for the silent-success pattern" and the upgrade-queue
  split as open `[ ]` items, even though both are already implemented in the current uncommitted
  diff (verified against `docs/plans/2026-07-16-polyget-features-and-improvements.md`'s Tasks 7 and
  10).
- `requirements.txt` has no `pytest` entry and no `requirements-dev.txt` exists — a clean `pip
  install -r requirements.txt && pytest` per `AGENTS.md`'s documented setup fails with `pytest:
  command not found`. Flagged by the untracked `codex_review.md`'s external review of `AGENTS.md`
  and confirmed still unaddressed.
- `AGENTS.md` and `codex_review.md` are untracked at repo root; decide whether `AGENTS.md` should be
  committed (it's otherwise accurate per spot-check) and whether `codex_review.md` should be
  archived/deleted once its one open finding (the pytest gap above) is resolved.

**Steps:**
1. Move `RIP_IT_APART_FIXPLAN_2026-07-12.md` into `docs/plans/` (renamed to match the dated-doc
   convention) or delete it now that all 3 items are shipped and confirmed on `master`.
2. Update `run.py`'s docstring to reference PolyGet by name.
3. Update or remove the "adapted from upgrader-tui" line in `CLAUDE.md` once confirmed stale by a
   maintainer.
4. Fix the stale mechanism name in `app/core/coordinator.py:50-51`'s comment to say
   `start_new_session=True` instead of `preexec_fn=os.setsid`.
5. Update `ROADMAP.md`'s "Improvements" checklist to mark the sync/blueprint-failure-audit and
   upgrade-queue-split items as done, once the current uncommitted diff is committed.
6. Add a `requirements-dev.txt` (or a `[dev]` extras section) including `pytest`, and update
   `AGENTS.md`/README setup instructions to reference it.
7. Commit `AGENTS.md` if it's confirmed accurate, and delete/archive `codex_review.md` once its
   pytest-gap finding is resolved by step 6.

---

## Known coverage gaps

- **Pacman's upgrade-command path** (`get_upgrade_command()` → `pkexec pacman -Syu --noconfirm`)
  was reasoned to be safe from the `-Qu`-style inverted-exit-code convention, but this was never
  executed against a real pacman binary — this audit session ran on the Fedora/Asahi machine, and
  pacman isn't installed there. Verify directly on the CachyOS/Arch machine before treating this as
  fully confirmed.
- **Finding B3 (Task 3) and Finding B9 (Task 5)** both carry `[reasoned from code — not verified by
  direct execution]` qualifiers: the underlying code facts (raw `sudo` catalog entries; `.list`-only
  glob) are solid and grep-confirmed, but their user-facing consequences (install failing/hanging on
  Arch; the Repositories page returning empty on modern Ubuntu/Debian) were not reproduced live in
  this audit session — there was no Arch machine and no live Debian/Ubuntu 24.04+ system available
  (this project's cloud sandbox runs a fixed Ubuntu base per CLAUDE.md but wasn't used to check the
  actual on-disk `/etc/apt/` layout there).
- **Finding B1 (Task 1)**'s "permanently disables the button" consequence is a deterministic logic
  trace through `scan_all()`/`handle_scan_finished()`, not an observed hang — no test or live run
  actually stalled a subprocess and watched the button stay disabled.
- **Churn-based hotspotting blind spot**: this audit's stage-1 recon used commit-churn to prioritize
  files for review, which structurally misses brand-new files with high inherent risk and zero
  history — `app/core/drivers/apt.py` (a recent addition) was nearly missed this way and required a
  dedicated follow-up pass. Worth a standing reminder for future audits of this repo: always check
  the newest files individually, not just the highest-churn ones.
- Not independently re-verified this pass (carried forward as still-solid from prior verification):
  the driver auto-discovery/registry pattern, `SubprocessCoordinator`'s termination fallback chain,
  `BlueprintManager`'s YAML strict-reject parsing, the Flatpak OCI ghost-update filter, and the
  Julia driver's argument-passing fix — all confirmed this pass and not flagged as needing rework;
  see the Context section above.

## Definition of done

- Task 1: DNF, pnpm, Yarn, Flatpak's `list_installed()`, and cpanm/dart_pub/hex/poetry's
  `list_installed()` all wrap their subprocess calls in `asyncio.wait_for`; a timeout raises
  `RuntimeError` instead of hanging; a test per driver proves it.
- Task 2: `_check_package()` no longer silently swallows per-package check failures into a false
  "up to date"; a test proves a corrupted/failed per-package check surfaces as an error, not a
  false negative.
- Task 3: no Arch-family `manager_catalog.yaml` self-install entry begins with `"sudo"`; a test
  enforces this; manually confirmed on CachyOS once available.
- Task 4: the TUI's sudo-password-retry path either works against a real pkexec-no-agent failure,
  or has been deliberately removed with updated docs — no dead, unreachable branch remains.
- Task 5: `list_repos()` correctly parses at least one realistic deb822 `.sources` fixture; test
  added; ideally validated against a real Ubuntu 24.04+/Debian 12+ system or the cloud sandbox.
- Task 6: two rapid searches/category-changes/repo-loads resolve to the newer result, not
  whichever happened to finish last; tests added for all three worker types.
- Task 7: install-manager, install-package, and repo-action buttons cannot launch a second
  concurrent identical subprocess via a rapid double-click; `active_operation` itself has a
  regression test.
- Task 8: the pipx index cache write is atomic (temp file + rename); concurrent-write test added.
- Task 9: a no-space `#deb-src` line appears in `list_repos()`'s output as disabled, not dropped.
- Task 10: `check_updates()` and `list_installed()` agree on multiarch package-name format.
- Task 11: `requirements.txt` has explicit upper bounds or documented tested versions.
- Task 12: CLAUDE.md's three "known bugs" accurately describe current, verified reality.
- Task 13: stray root-level doc moved/removed, stale docstrings/comments corrected, ROADMAP.md
  checklist current, `requirements-dev.txt` exists with `pytest`, and `AGENTS.md`/`codex_review.md`
  are either committed or removed as appropriate.
