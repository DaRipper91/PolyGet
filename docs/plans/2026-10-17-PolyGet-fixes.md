# PolyGet: Fix plan from 2026-10-17 audit

> **Implement task-by-task, in order.** Task 1 (the hanging blueprint-GUI test) first — it blocks the suite from running green and any CI work that follows.

**Context:** PolyGet is a PySide6 desktop app (plus a Textual TUI and headless CLI) unifying 27 package-manager drivers behind one dashboard, repo/remote management, and blueprints, developed on two machines (Asahi beta + CachyOS) feeding one `master`. This pass covered recon, core verification, a bug hunt (including a targeted re-check of previously flagged items), and a strengths scout across the repo on branch `Asahi/BETA-FEATURES`. Already solid and not to be re-litigated: declarative `pkgutil` driver discovery via `@register_manager` (no manual import list); `run_capture` centralizing the no-shell/timeout/`ok_codes`/`DriverError` contract; `DriverError`/`describe_error` making scan failures surface; `PackageManager.still_outdated` re-query after upgrade; `ExecutionWorker` process-group cancellation via `SubprocessCoordinator.killpg`; crash-tolerant JSONL history with recomputed success; versioned `settings_store` with recursive key merge; and tests targeting the fragile subprocess/exit-code paths.

---

## Task 1 — Fix hanging blueprint-GUI test (unmocked stderr stream)

**Problem:** `tests/test_blueprint_gui.py::test_sync_system_to_blueprint_with_drift` hangs forever. `ExecutionWorker` reads stderr on a separate stream after the pkexec→sudo change (`6ae271f`), but the test only sets `mock_proc.stdout.readline` side_effect; the unmocked `AsyncMock.readline` for `stderr` never returns `b""`, so `read_stream` loops forever. Cited at the test def (`tests/test_blueprint_gui.py:452`) and the mock block (`tests/test_blueprint_gui.py:476-485`). Verified by a 40s timeout and by a patched copy adding `mock_proc.stderr.readline = AsyncMock(side_effect=[b""])`, which passes. Severity: medium. [VERIFIED]

**Steps:**
1. In `tests/test_blueprint_gui.py`, add `mock_proc.stderr.readline = AsyncMock(side_effect=[b""])` (or the appropriate sequence of stderr lines) to the mock setup for `test_sync_system_to_blueprint_with_drift`.
2. Run `QT_QPA_PLATFORM=offscreen pytest tests/test_blueprint_gui.py::test_sync_system_to_blueprint_with_drift` and confirm it passes within a few seconds.
3. Re-run the full suite (`QT_QPA_PLATFORM=offscreen pytest`) and confirm 402 passed, 0 hung.

---

## Task 2 — Surface ImportError in manager discovery instead of swallowing

**Problem:** `app/core/manager.py:279-280` and `298-299` — `discover_managers()` and `get_all_managers()` wrap `importlib.import_module("app.core.drivers")` in `except ImportError: pass`. A broken driver import leaves the app with zero managers and no error, silently. Severity: medium. [VERIFIED]

**Steps:**
1. Replace the bare `except ImportError: pass` with logging (e.g., `logging.exception`/`logging.error`) of the import failure, and re-raise or otherwise make the failure observable (return an error indicator / set a flag) so the GUI/CLI can surface it rather than presenting an empty manager list as "no managers installed."
2. Add a test that injects a broken driver import and asserts the failure is reported (not silently swallowed).
3. Run `QT_QPA_PLATFORM=offscreen pytest tests/test_manager.py` (and any discovery tests) to confirm no regression.

---

## Task 3 — Make pkexec→sudo fallback authenticate (GUI path)

**Problem:** `app/ui/main_window.py:210-266` (`ExecutionWorker.run_with_fallback`) + `app/core/sudo_secret.py:load()`. `load()` returns `None` when no keyring entry exists, but the retry builds a `sudo -S` command and calls `run_once(sudo_cmd, password=None)`; with `password is None`, stdin is set to `DEVNULL`, so on a non-NOPASSWD sudoers entry sudo has no password source and the retry cannot succeed (verified: `sudo -n true` exits 1 with "a password is required" on this machine). The TUI path (`app/ui/tui.py:577-690`) handles `None` by prompting the user; the gap is GUI-only. Severity: medium. [VERIFIED]

**Steps:**
1. In `ExecutionWorker.run_with_fallback`, when the stored password is `None`, either prompt the user for a password (reuse the TUI's approach) or surface a clear failure instead of attempting a `DEVNULL`-stdin retry that cannot succeed.
2. If prompting, feed the entered password (possibly `""` for NOPASSWD) over stdin to `sudo -S`.
3. Add a test exercising the `password is None` path end-to-end (mocked) asserting it does not silently attempt `DEVNULL` auth.
4. Cross-reference Strength #5 (the fallback's marker isolation and process-group cancellation are sound; only the `None`-password path is broken).

---

## Task 4 — Surface pipx subprocess failures instead of returning []

**Problem:** `app/core/drivers/pipx.py:113-135` (`check_updates`). `pipx list --short` is run but its returncode is never checked; on nonzero exit stdout is empty, `packages` is empty, and the method returns `[]`, indistinguishable from "no updates." Reproduced: mocked `pipx list --short` returning rc=1 yielded `[]`. Contrast `list_installed`/`list_installed_versions`, which raise `DriverError`. Also `check_updates` raises `RuntimeError` (not `DriverError`) and `_check_package` raises `RuntimeError`, inconsistent with the driver contract. Severity: medium. [VERIFIED]

**Steps:**
1. In `check_updates`, check `proc.returncode`; on nonzero, raise `DriverError` (with stderr detail, consistent with `run_capture`/other drivers).
2. Align exception types: raise `DriverError` rather than `RuntimeError` in `check_updates` and `_check_package`.
3. Add a test (in `tests/test_pipx_driver.py`) asserting a nonzero `pipx list --short` raises `DriverError` rather than returning `[]`.
4. Note residual gap: stdout format parsing of `pipx list --short` was not fixture-tested beyond the rc=1 path; add a fixture-based parsing test if feasible.

---

## Task 5 — Surface Flatpak subprocess failures instead of returning []

**Problem:** `app/core/drivers/flatpak.py:67-86` (`check_updates`) — only `stdout` emptiness is tested; `proc.returncode` is ignored, so a failed `remote-ls --updates` yields `[]`. Same masking in `list_installed` (~154) and `list_installed_versions` (~182), which return `[]`/`{}` on nonzero. Also `app/core/drivers/flatpak.py:38-41` — installed-map parsing checks only `if list_stdout:`; a failed `flatpak list` with empty stdout leaves `installed_map` empty and every remote entry is reported as an update. Inconsistent with the "failures surface as failed" design principle. Severity: medium (check_updates/list_installed) / low (installed-map). [VERIFIED]

**Steps:**
1. In `check_updates`, `list_installed`, and `list_installed_versions`, check `proc.returncode` and raise `DriverError` (with stderr detail) on nonzero exit instead of returning `[]`/`{}`.
2. In the installed-map parsing path, treat a failed/empty `flatpak list` as an error condition rather than silently treating all remote entries as updates.
3. Add tests (new `tests/test_flatpak_driver.py` if needed) covering nonzero returncodes for `remote-ls --updates`, `list`, and installed-map parsing, since no flatpak driver test file currently exists.
4. Note: findings rest on repro + code reading because no `tests/test_flatpak_driver.py` exists; add coverage to lock in the fix.

---

## Task 6 — Fix version_scan `_normalize_name` over-stripping `lib` prefix

**Problem:** `app/core/version_scan.py:164-174` (`_normalize_name`). The loop strips any of `python-`, `node-`, `perl-`, `ruby-`, `lib` on first match with no word boundary, so `libreoffice` → `reoffice` (verified: `_normalize_name("libreoffice") == "reoffice"`). Could cause false cross-manager name matches. Severity: medium. [VERIFIED]

**Steps:**
1. Make the `lib` prefix strip word-boundary aware (e.g., match `lib` followed by a separator or a capital/uppercase letter, or require `lib-`/`lib_`), so `libreoffice` is not mangled while `libfoo`-style names still normalize.
2. Add a regression test in `tests/test_version_scan.py` covering `libreoffice` (unchanged) and a genuine `libfoo` (stripped).
3. Run `QT_QPA_PLATFORM=offscreen pytest tests/test_version_scan.py` (32 tests) to confirm.

---

## Task 7 — Fix version_scan cross-ecosystem version comparison

**Problem:** `app/core/version_scan.py:221-265` (`_best_version`/`_version_greater`). `_version_greater(manager_name, v1, v2)` dispatches the parser on `manager_name` alone, so in a mixed group a distro version and a runtime version are parsed with whichever manager happens to be the candidate. Reproduced: a group `{Pacman: 1.0.0-1, Pipx: 2.0.0, Cargo: 3.0.0}` yields a suggestion naming Cargo as newest (cross-ecosystem-unverified) even though Pipx and Cargo are different ecosystems bridged only through the distro. Severity: medium. [VERIFIED]

**Steps:**
1. Ensure each version is parsed with its own manager's parser (pass the owning manager name into `_version_greater` for each side, or compare parsed objects), rather than using one candidate manager's parser for both.
2. Consider gating cross-ecosystem comparisons behind a trusted-pair check (`_pair_comparable`/`_is_trusted_pair`) so a distro package and a language-runtime package are not declared "newer" across ecosystems without evidence.
3. Add a regression test reproducing the mixed-ecosystem group and asserting it does not produce a spurious "Cargo newest" suggestion.
4. Run `tests/test_version_scan.py`.

---

## Task 8 — Add CI workflow running the test suite

**Problem:** Repository has no `.github/workflows/` (or any build/release workflow); the 402-test suite runs only locally. Severity: medium. [VERIFIED]

**Steps:**
1. Create `.github/workflows/tests.yml` that checks out the repo, sets up Python 3.10+, installs `requirements.txt` and `requirements-dev.txt`, and runs `QT_QPA_PLATFORM=offscreen pytest` (excluding or handling the hanging test until Task 1 lands).
2. After Task 1, drop any deselect and run the full suite.
3. Ensure the workflow fails on test failures; optionally add a matrix for Python versions.

---

## Task 9 — Wire debug_log.emit into remaining workers

**Problem:** `app/ui/main_window.py` — `debug_log.emit` is called only in `ExecutionWorker`; `ScanWorker` (~78), `VersionCheckWorker` (~112), `FetchReposWorker` (~139), `SearchWorker` (~281), `CategoryWorker` (~333), and `FetchInstalledWorker` (~441) do not publish to the debug stream, so `--debug`/Debug Console misses scan/repo/search/install activity. Merged with Core Verification #6 (same gap, differing only in line citations). Severity: low. [VERIFIED]

**Steps:**
1. Add `debug_log.emit(...)` calls (gated by `debug_log.enabled()`) at the start/completion/error points of each listed worker, consistent with `ExecutionWorker`'s usage.
2. Ensure CLI-only use still works (debug_log is Qt-optional; imports PySide6 inside try/except).
3. Add/adjust tests if any worker tests assert debug output; otherwise verify manually with `python run.py --debug managers`.

---

## Task 10 — Tighten pkexec failure detection (avoid substring false positives)

**Problem:** `app/ui/main_window.py:185-190` (`_looks_like_pkexec_no_agent_failure`) and `app/ui/tui.py:100-115` use `marker in lowered` over stderr to detect a pkexec failure caused by no bound polkit agent. A real command failure whose stderr happens to contain one of the markers could be misclassified as an auth-agent problem and masked by a sudo retry. Duplicated in both files (same constants/heuristic). Severity: low. [VERIFIED]

**Steps:**
1. Replace the loose substring check with a more precise match (e.g., anchor markers to known pkexec/polkit error phrasing, or match full lines / exit codes) in both `app/ui/main_window.py` and `app/ui/tui.py`, keeping the two in sync.
2. Add tests covering a command failure whose stderr contains a marker but is not an auth-agent problem, asserting it is not retried as sudo.

---

## Task 11 — Tighten DNF repo-list status check (exact token, not substring)

**Problem:** `app/core/drivers/dnf.py:294` — `if "disabled" in status_str` could misfire on a status token that merely contains the substring. Verified on this machine: `dnf repolist --all --quiet` emits only exactly `enabled` and `disabled` tokens, so no current misfire, but the check is fragile for portability (a future DNF emitting e.g. "disabled (vendor)" or a localized status would be mishandled). Severity: low. [VERIFIED — no current misfire; portability caveat]

**Steps:**
1. Change the check to `status_str == "disabled"` (or `status_str.startswith("disabled")` if a guarded variant is preferred) in `app/core/drivers/dnf.py`.
2. Add a test in `tests/test_dnf_driver.py` covering the status parsing with the tightened check.

---

## Task 12 — Guard Flatpak ghost-update filter against coincidental prefix matches

**Problem:** `app/core/drivers/flatpak.py:95-103` — `if alt_id and remote_commit and (alt_id.startswith(remote_commit) or remote_commit.startswith(alt_id))` skips the entry whenever one hash is a prefix of the other, with no length guard. A truncated alt-id or coincidental prefix silently drops a real update. Severity: low. [VERIFIED — logic inspection]

**Steps:**
1. Add a minimum-length guard (e.g., require both hashes to be at least N characters and the shorter to be a substantial prefix) before treating one as a prefix of the other, or require exact equality of truncated forms.
2. Add a test covering a coincidental short-prefix case asserting the update is not dropped.

---

## Task 13 — Check Flatpak `list` returncode before building installed map

**Problem:** `app/core/drivers/flatpak.py:38-41` — `if list_stdout:` only; a failed `flatpak list` with empty stdout leaves `installed_map` empty and every remote entry is reported as an update. Severity: low. [VERIFIED — logic inspection]

**Steps:**
1. Check `proc.returncode` for the `flatpak list` call; on nonzero exit, raise `DriverError` (or at least do not build an empty installed map that masquerades as "nothing installed").
2. Coordinate with Task 5 so all flatpak subprocess paths are consistent.

---

## Task 14 — Remove dead `_is_trusted_pair` (or wire it) in version_scan

**Problem:** `app/core/version_scan.py:63-85` — `_is_trusted_pair` is defined but never called anywhere in `app/` or `tests/`; untrusted-pair handling actually lives in `_pair_comparable`. Two sources of truth; maintenance hazard. Not a runtime defect. Severity: low. [VERIFIED]

**Steps:**
1. Either delete `_is_trusted_pair` and consolidate on `_pair_comparable`, or wire `_is_trusted_pair` into the comparison path (and remove the duplicate logic in `_pair_comparable`).
2. Run `tests/test_version_scan.py` to confirm no regression.

---

## Task 15 — Fix version_scan `_parse_system_version` pre-release/pkgrel handling [UNVERIFIED]

**Problem:** `app/core/version_scan.py:197-219` — `_parse_system_version` strips pkgrel by `rsplit("-")`, so a version like `1.0.0-rc1` (no pkgrel) is reduced to `1.0.0`, discarding the pre-release marker; only relevant for distro strings that embed pre-release tags. Tagged `[UNVERIFIED — worth checking]`; no fixture exercised it. Severity: low. [UNVERIFIED]

**Steps:**
1. Capture real distro version strings (including any pre-release-tagged ones) and determine whether pkgrel stripping ever collides with a pre-release suffix.
2. If confirmed, change the stripping to only remove a trailing pkgrel when the suffix matches a numeric pkgrel pattern (e.g., `-<digits>`), preserving `-rc1`-style pre-release markers.
3. Add a test covering both `1.0.0-2` (pkgrel stripped) and `1.0.0-rc1` (preserved).

---

## Task 16 — Remove hardcoded personal path from tracked skill file

**Problem:** `.claude/skills/polyget/SKILL.md:12` bakes `/home/daripper/Projects/PolyGet/...` into a tracked file, so the skill only works on the original author's machine. Severity: low. [VERIFIED]

**Steps:**
1. Replace the hardcoded absolute path with a relative path or a placeholder/variable resolved at runtime (e.g., repo root detection).
2. Verify the skill still functions on a different checkout path.

---

## Known coverage gaps

Disclosed by the critic pass; these were not fully checked this pass and are not claimed as clean:

- **`app/ui/tui.py` (798 lines)** — partially reviewed. Sudo flow (no NOPASSWD/auth gap; prompts correctly) and pkexec marker duplication verified. Residual gap: upgrade path, polkit handling beyond markers, rendering, and the rest of the module were not deeply reviewed.
- **`app/cli.py` (633 lines)** — still only surface-level: command registration (15 commands → handlers) and CLI smoke verified; dispatcher/JSON-output/error-code logic not deep-reviewed.
- **pipx stdout format parsing** — `check_updates` parses `pipx list --short` output; only the rc=1 path was repro-tested; stdout format parsing remains code-read only.
- **Flatpak driver test coverage** — no `tests/test_flatpak_driver.py` exists (only `tests/test_flatpak_search.py`), so flatpak masking/filter findings rest on repro + code reading.
- **Secret content scan** — manual regex scan over 153 tracked files (no matches); `gitleaks`/`trufflehog`/`pip-audit` not installed and not run. Permanent coverage limit, not a code defect.
- **GUI ExecutionWorker paths** — verified that each code path *calls* `ExecutionWorker`, but repo-toggle/sync/install GUI paths were not exercised end-to-end; covered only by isolated `ExecutionWorker` unit tests.
- **version_scan #5** (`_parse_system_version` pkgrel stripping) — carried forward as `[UNVERIFIED]`; low severity, no fixture exercised.

## Definition of done

- Task 1: `tests/test_blueprint_gui.py::test_sync_system_to_blueprint_with_drift` passes; full suite reports 402 passed, 0 hung.
- Task 2: manager discovery logs/reports import failures; a test confirms a broken driver import is surfaced, not swallowed.
- Task 3: GUI pkexec→sudo fallback either prompts for a password or fails clearly when no stored password exists; no `DEVNULL`-stdin retry on a non-NOPASSWD entry; test covers the `None` path.
- Task 4: pipx `check_updates` raises `DriverError` on nonzero exit; exception types aligned to `DriverError`; test added.
- Task 5: flatpak `check_updates`/`list_installed`/`list_installed_versions` raise `DriverError` on nonzero exit; empty installed map no longer masquerades as "nothing installed"; tests added.
- Task 6: `_normalize_name("libreoffice")` no longer returns `"reoffice"`; regression test added.
- Task 7: mixed-ecosystem group no longer produces a spurious cross-ecosystem "newest" suggestion; regression test added.
- Task 8: `.github/workflows/tests.yml` runs `QT_QPA_PLATFORM=offscreen pytest` and fails on failures.
- Task 9: all six listed workers emit to `debug_log` when enabled; CLI `--debug` shows their activity.
- Task 10: pkexec marker detection no longer misclassifies unrelated failures in either file; test added.
- Task 11: DNF status check uses exact token match; test added.
- Task 12: flatpak ghost-update filter has a length guard; test added for coincidental prefix.
- Task 13: flatpak `list` returncode checked before building installed map.
- Task 14: `_is_trusted_pair` either removed or wired in, single source of truth; tests pass.
- Task 15: `_parse_system_version` preserves pre-release markers (or finding closed with evidence); test added.
- Task 16: no hardcoded personal paths remain in `.claude/skills/polyget/SKILL.md`; skill works on another checkout path.
- Full suite green (`QT_QPA_PLATFORM=offscreen pytest`) after all tasks.