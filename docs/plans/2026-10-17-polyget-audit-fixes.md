# PolyGet — Audit Fix Plan

**Project:** PolyGet
**Branch:** CachyOS/BETA-FEATURES
**Date:** 2026-10-17
**Source:** Approved audit scratch file `.audit/SCRATCH.md` (sections 01–05), Stage 5 clean pass = Yes.
**Status:** Plan only — no application source code modified. Written by Stage 6 (Fix Plan Writer) of the rip-it-apart audit chain.
**Precondition met:** Stage 5 (`05 — Critic Pass`) reports `Clean pass? Yes`. All citations verified against the live codebase.

---

## Overview

This plan converts all 10 approved bug findings from `## 03 — Bug Hunt` into concrete, actionable tasks, plus one stale-reference documentation note and a strengths-preservation section. Tasks are organized by severity (Medium first, then Low), then alphabetically by file. Each task has a file:line citation, a concrete failure-mode description, severity, a specific suggested fix, verification steps, and any ordering dependencies.

No Critical or High findings were approved. All Medium findings are race/concurrency conditions; all Low findings are silent failures, an off-by-one, and dependency drift.

## Task Index

| Task ID | File:Line | Category | Severity |
|---------|-----------|----------|----------|
| FIX-01 | `app/core/coordinator.py:43-68` | Race condition | Medium |
| FIX-02 | `app/core/history_store.py:29-30` | Race condition | Medium |
| FIX-03 | `app/core/settings_store.py:91-93` | Race condition | Medium |
| FIX-04 | `app/core/ignore_store.py:34-38` | Race condition | Medium |
| FIX-05 | `app/core/drivers/aur.py:72` | Off-by-one | Low |
| FIX-06 | `app/core/drivers/dnf.py:69-70` | Silent failure | Low |
| FIX-07 | `app/core/drivers/pnpm.py:23-53` | Dependency drift | Low |
| FIX-08 | `app/ui/main_window.py:71` | Silent failure | Low |
| FIX-09 | `app/ui/tui.py:552` | Silent failure | Low |
| FIX-10 | `app/core/coordinator.py:63` | Silent failure | Low |

Reference note (documentation only, no code change): `assets/polyget.desktop` hardcoded `Polyget` path.

---

## Medium — Race Conditions

### FIX-01 — `app/core/coordinator.py:43-68` — PID-reuse race in `terminate_all()`

**Failure mode:** `terminate_all()` copies the tracked PIDs under lock (line 46), releases the lock, then iterates and kills each PID's process group without the lock (lines 48–64). Every registered PID is a process-group leader (spawned with `start_new_session=True`). If a PID is reused by a new session-leader process between the copy and the kill, `os.killpg(pid, SIGTERM)` could terminate an unrelated process group.

**Severity:** Medium

**Suggested fix:** Hold the lock for the entire kill loop, or re-validate each PID under the lock immediately before calling `os.killpg`. Specifically:
- Acquire `self._lock` once at the start of `terminate_all()`.
- Snapshot PIDs under the lock, iterate the snapshot killing each PID's process group while still holding the lock (or re-check `pid in self._processes` under the lock right before each `os.killpg` call).
- Only call `self._processes.discard(pid)` / remove from tracking after a successful kill attempt, still under the lock.
- Do not release the lock between copy and kill. Keep `os.killpg` / `os.kill` calls inside the critical section; they are fast syscalls and will not meaningfully serialize shutdown.

**Verification:**
- Add a unit test `tests/test_coordinator.py::test_terminate_all_holds_lock_until_kills_complete` that registers a fake process-group leader, simulates PID reuse by inserting a new process with the same PID into `self._processes` concurrently, and asserts `os.killpg` is never called with a reused PID.
- Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_coordinator.py -q`
- Run: `QT_QPA_PLATFORM=offscreen python3 -m pytest tests -q` (full suite) — must remain 376 passed, 0 failed.

**Depends on:** None (standalone; `coordinator.py` is pure stdlib).

---

### FIX-02 — `app/core/history_store.py:29-30` — JSONL append without file locking

**Failure mode:** `record_upgrade()` opens `history.jsonl` in append mode and writes one line without file locking (lines 29–30). If the GUI and CLI (or two GUI instances) run concurrently, appends could interleave and corrupt JSONL lines. Each write is a single `write()` call (typically atomic on local filesystems for small writes), but there is no guarantee under concurrent access. The test suite has no concurrency tests for `history.jsonl`, so exploitability under real concurrent use is unverified (per `## 05` disclosure).

**Severity:** Medium

**Suggested fix:** Guard all writes to `history.jsonl` with an `asyncio.Lock()` (module-level, matching the pattern already used in `pipx.py:198` `_index_lock`). In `record_upgrade()`:
- Acquire the module-level lock before opening the file.
- Open, write one line, flush, close — all while holding the lock.
- Release the lock after write completes.
- Keep the same JSONL append behavior; only add serialization.

**Verification:**
- Add a unit test `tests/test_history_store.py::test_concurrent_record_upgrade_no_interleaving` that spawns multiple concurrent `record_upgrade()` calls writing distinct lines and asserts every written line is valid JSON on its own line with no interleaved/corrupted content.
- Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_history_store.py -q`
- Run: `QT_QPA_PLATFORM=offscreen python3 -m pytest tests -q` (full suite) — must remain 376 passed, 0 failed.

**Depends on:** None.

---

### FIX-03 — `app/core/settings_store.py:91-93` — `settings.json` write without locking

**Failure mode:** `_save()` writes `settings.json` via `write_text()` without locking (lines 91–93). `set()` calls `_save()` on every change. Concurrent writes from multiple processes (GUI + CLI) could corrupt the file (partial writes, lost updates). Same class of issue as FIX-02/FIX-04; no concurrency tests cover `settings.json` (per `## 05` disclosure).

**Severity:** Medium

**Suggested fix:** Guard `_save()` writes to `settings.json` with a module-level `asyncio.Lock()`. In `_save()`:
- Acquire the lock before `write_text()`.
- Write, flush, release.
- Since `set()` calls `_save()` on every change, the lock serializes all mutations so concurrent `set()` calls from GUI and CLI cannot interleave partial writes or lose updates.

**Verification:**
- Add a unit test `tests/test_settings_store.py::test_concurrent_set_no_lost_updates` that calls `set()` concurrently from multiple coroutines with distinct keys and asserts all keys are present and correct after completion.
- Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_settings_store.py -q`
- Run: `QT_QPA_PLATFORM=offscreen python3 -m pytest tests -q` (full suite) — must remain 376 passed, 0 failed.

**Depends on:** None.

---

### FIX-04 — `app/core/ignore_store.py:34-38` — `ignored_packages.json` write without locking

**Failure mode:** `add()` (lines 34–35) and `remove()` (lines 37–38) write `ignored_packages.json` via `_save()` without locking. Same concurrent-write corruption risk as FIX-02/FIX-03. The store uses a Python `set` of `(manager, package)` tuples (inherently deduped in-memory), but concurrent file writes can still corrupt on-disk state.

**Severity:** Medium

**Suggested fix:** Guard `_save()` writes to `ignored_packages.json` with a module-level `asyncio.Lock()`. In `_save()`:
- Acquire the lock before `write_text()`.
- Write, flush, release.
- Apply to both `add()` and `remove()` paths since both call `_save()`.

**Verification:**
- Add a unit test `tests/test_ignore_store.py::test_concurrent_add_remove_no_corruption` that runs concurrent `add()` and `remove()` calls and asserts the resulting file parses as valid JSON containing exactly the expected set.
- Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_ignore_store.py -q`
- Run: `QT_QPA_PLATFORM=offscreen python3 -m pytest tests -q` (full suite) — must remain 376 passed, 0 failed.

**Depends on:** None.

---

## Low — Silent Failures / Off-by-One / Dependency Drift

### FIX-05 — `app/core/drivers/aur.py:72` — Off-by-one range skip

**Failure mode:** `for i in range(0, len(lines) - 1, 2)` iterates AUR search/installed output in pairs (header line + description line). If `pacman -Qm` or `paru/yay -Ssa` output has an odd number of lines, `len(lines) - 1` excludes the final line, which is silently skipped. An installed package or search result could be dropped without any indication.

**Severity:** Low

**Suggested fix:** Change the loop bound so the final line is not unconditionally dropped:
- Replace `range(0, len(lines) - 1, 2)` with `range(0, len(lines) - (len(lines) % 2), 2)`, OR
- Iterate pairs explicitly: `for i in range(0, len(lines) - 1, 2)` keeps pairing but add handling for a trailing unpaired line (e.g., treat it as a header with empty description, or log via `describe_error`/notification).
- Prefer the minimal change: `range(0, len(lines) - (len(lines) % 2), 2)` processes all complete pairs and ignores only a genuine trailing odd line (which cannot form a pair anyway).

**Verification:**
- Add a unit test `tests/test_aur_driver.py::test_aur_parse_odd_line_count` that feeds `pacman -Qm` / `paru -Ssa` output with an odd number of lines and asserts the last entry is either paired correctly or handled without dropping data.
- Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_aur_driver.py -q`
- Run: `QT_QPA_PLATFORM=offscreen python3 -m pytest tests -q` (full suite) — must remain 376 passed, 0 failed.

**Depends on:** None.

---

### FIX-06 — `app/core/drivers/dnf.py:69-70` — Vendor-change swallow

**Failure mode:** `_mark_vendor_blocked` wraps the vendor-change detection subprocess calls (`dnf --dump-main-config`, `dnf repoquery`, `rpm -q`) in `except Exception: return updates` (lines 69–70). If any call fails (timeout, missing `rpm`, D-Bus lock), the exception is swallowed and updates are returned unflagged. Packages that should be marked "vendor change blocked" appear as normal upgrades; the user may attempt an upgrade DNF will silently skip. Documented as "best-effort" but still a silent failure with user impact.

**Severity:** Low

**Suggested fix:** Do not swallow the exception into a silent `return updates`. Instead:
- Catch the exception, log it through the existing `_log()` mechanism (or `describe_error`), and return `updates` unchanged so the caller still gets the package list — but surface the detection failure visibly.
- Add a `vendor_change_detection_failed: bool` flag (or equivalent) to the returned result so the UI can show a warning that vendor-change blocking could not be verified for those packages.
- Keep the "best-effort" semantics (don't block the upgrade), but make the failure observable rather than silent.

**Verification:**
- Add a unit test `tests/test_dnf_driver.py::test_mark_vendor_blocked_subprocess_failure_logged` that mocks the subprocess calls to raise and asserts the exception is logged (not swallowed) and updates are still returned.
- Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_dnf_driver.py -q`
- Run: `QT_QPA_PLATFORM=offscreen python3 -m pytest tests -q` (full suite) — must remain 376 passed, 0 failed.

**Depends on:** None.

---

### FIX-07 — `app/core/drivers/pnpm.py:23-53` — Shim detection dependency drift

**Failure mode:** `_needs_shell_fallback()` detects pnpm 11+ placeholder shims by reading the first 2 bytes of the `pnpm` binary and checking for shebang (`#!`) or ELF/Mach-O magic bytes (lines 23–53). If pnpm changes its placeholder shim format in a future version (e.g., starts with `#!`), this detection could misclassify the binary, causing `Exec format error` or an incorrect `sh` invocation. This is a version-specific workaround tightly coupled to pnpm's internal binary format.

**Severity:** Low

**Suggested fix:** Make the shim detection robust to format drift:
- Instead of hardcoding magic-byte checks, attempt to execute `pnpm` directly first via `asyncio.create_subprocess_exec`.
- On `Exec format error` / `FileNotFoundError` / nonzero exit indicating a shim mismatch, fall back to invoking `sh -c 'pnpm ...'` (or the detected shell wrapper) as a secondary attempt.
- Alternatively, detect the shim by running `pnpm --version` and checking for a known-good output, falling back to `sh` only when that fails.
- Remove the brittle first-2-bytes magic-byte check; replace with behavior-based detection that does not depend on pnpm's internal binary layout.

**Verification:**
- Add a unit test `tests/test_pnpm_driver.py::test_needs_shell_fallback_exec_format_error` that mocks `create_subprocess_exec` to raise `Exec format error` on direct execution and asserts the fallback path is taken.
- Add a unit test `tests/test_pnpm_driver.py::test_needs_shell_fallback_direct_success` that asserts direct execution succeeds without fallback when `pnpm --version` returns valid output.
- Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_pnpm_driver.py -q`
- Run: `QT_QPA_PLATFORM=offscreen python3 -m pytest tests -q` (full suite) — must remain 376 passed, 0 failed.

**Depends on:** None.

---

### FIX-08 — `app/ui/main_window.py:71` — Icon read swallow

**Failure mode:** `_parse_icon_from_file` wraps `.desktop` file reading in `except Exception: pass` (line 71). If a desktop file can't be read, the icon lookup silently fails and returns `None`. Cosmetic only (missing icon), no functional impact.

**Severity:** Low

**Suggested fix:** Replace the bare `except Exception: pass` with targeted handling:
- Catch specific exceptions (`FileNotFoundError`, `PermissionError`, `OSError`) rather than all exceptions.
- Log the failure via the existing `_log()` mechanism so missing/unreadable `.desktop` files are observable in logs.
- Return `None` (current behavior preserved) but with the failure surfaced in logs for debugging.

**Verification:**
- Add a unit test `tests/test_main_window.py::test_parse_icon_from_file_unreadable_logged` that points `_parse_icon_from_file` at an unreadable/missing `.desktop` file and asserts a log entry is emitted and `None` is returned.
- Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_main_window.py -q`
- Run: `QT_QPA_PLATFORM=offscreen python3 -m pytest tests -q` (full suite) — must remain 376 passed, 0 failed.

**Depends on:** None.

---

### FIX-09 — `app/ui/tui.py:552` — kdeconnect silent failure

**Failure mode:** `_send_phone_notification` wraps all `kdeconnect-cli` calls (device lookup + ping message) in `except Exception: pass` (line 552). If the phone notification fails (kdeconnect not running, device unreachable, D-Bus error), the user receives no indication. Silent by design, but a silent failure nonetheless.

**Severity:** Low

**Suggested fix:** Replace `except Exception: pass` with observable handling:
- Catch specific exceptions (`FileNotFoundError` for missing `kdeconnect-cli`, `subprocess.SubprocessError`/`OSError` for D-Bus or device errors).
- Log the failure via the existing `_log()` mechanism so the failure is observable in logs.
- Optionally surface a non-blocking TUI notification (via the existing toast/notification system) telling the user phone notification could not be sent.
- Do not make notification failure block the upgrade flow — keep it best-effort but observable.

**Verification:**
- Add a unit test `tests/test_tui.py::test_send_phone_notification_kdeconnect_failure_logged` that mocks `kdeconnect-cli` to raise and asserts a log entry is emitted and the TUI does not crash.
- Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_tui.py -q`
- Run: `QT_QPA_PLATFORM=offscreen python3 -m pytest tests -q` (full suite) — must remain 376 passed, 0 failed.

**Depends on:** None.

---

### FIX-10 — `app/core/coordinator.py:63` — Kill fallback swallow

**Failure mode:** `terminate_all` fallback `os.kill(pid, SIGTERM)` is wrapped in `except Exception: pass` (line 63). If the fallback kill fails after `os.killpg` also failed, the error is swallowed. The PID is still removed from the tracking set; low impact since cleanup proceeds regardless, but the failure is invisible.

**Severity:** Low

**Suggested fix:** Replace `except Exception: pass` with targeted handling:
- Catch `ProcessLookupError`, `PermissionError`, `OSError` specifically.
- Log the fallback-kill failure via the existing `_log()` mechanism so failed kill attempts are observable.
- Still remove the PID from tracking (cleanup proceeds regardless), but do not silently swallow the error.

**Verification:**
- Add a unit test `tests/test_coordinator.py::test_terminate_all_kill_fallback_failure_logged` that mocks `os.killpg` and `os.kill` to raise and asserts the error is logged and the PID is still removed from tracking.
- Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_coordinator.py -q`
- Run: `QT_QPA_PLATFORM=offscreen python3 -m pytest tests -q` (full suite) — must remain 376 passed, 0 failed.

**Depends on:** FIX-01 (both touch `coordinator.py`; implement FIX-01's lock change first so the fallback path lives inside the held lock).

---

## Stale Reference — Documentation Only (No Code Change)

### REF-01 — `assets/polyget.desktop` hardcoded `Polyget` path

**Observation:** `assets/polyget.desktop` lines 7–8 hardcode `Exec=/home/daripper/Projects/Polyget/.venv/bin/python ...` and `TryExec=/home/daripper/Projects/Polyget/.venv/bin/python`, using `Polyget` (lowercase g) which does not match the actual repo directory `PolyGet` (capital G). On a case-sensitive filesystem the committed desktop file would not resolve if used directly.

**Mitigation (already in place):** `scripts/install-desktop.sh` lines 40–43 `sed`-replaces both `Exec=` and `TryExec=` with `$REPO_ROOT/run.py` at install time, so the committed file is a template, not functional as-is. Verified by reading the script.

**Action:** Document only — no code change. The committed `assets/polyget.desktop` remains aspirational/templated; install-time sed fixes the path. No fix task required. Future refactors of `install-desktop.sh` should preserve this sed behavior.

---

## Strengths to Preserve (Do Not Change)

The following engineering strengths from `## 04 — Strengths` were verified and must be preserved — none of the fix tasks above should alter them:

1. **`DriverError` safety contract** — "empty ≠ failed" (`app/core/manager.py:17-30`). Drivers raise `DriverError` on genuine failure; return empty collections only when the query succeeded with nothing to report. Never swallow into `[]`.
2. **`ok_codes` in `run_capture`** — exit 1 means "nothing outdated," not failure (`app/core/manager.py:33-59`). Drivers pass `ok_codes=(0, 1)` for commands like `pacman -Qu` / `yay -Qua`.
3. **`describe_error` handles bare `asyncio.TimeoutError`** — `str(e) or type(e).__name__` prevents blank error messages (`app/core/manager.py:9-14`).
4. **Zero `shell=True`, argv-list-only subprocess calls** — verified across `app/`; `run.py` and `AGENTS.md` explicitly prohibit `shell=True`.
5. **Sudo password only in OS keyring, never on disk** — `app/core/sudo_secret.py:1-58`, service `polyget-sudo`; optional `keyring` import with quiet no-op fallback.
6. **pkexec TTY warning with sudo fallback** — `app/cli.py:122-124` and `app/ui/tui.py:658-667`; graceful degradation across interactive terminals, containers, and SSH.
7. **Single home for distro-family detection** — `app/core/distro.py:1-55`, `@functools.lru_cache`, reads `/etc/os-release` directly; nothing hardcoded per-distro in drivers or UI.
8. **Catalog design** — `has_driver:false` entries are honest gaps, not silent omissions (`app/core/catalog.py`; `manager_catalog.yaml`).
9. **Upgrade verification — re-check after exit-0** — `still_outdated()` (`manager.py:89-93`); CLI `cli.py:160-166`; GUI `main_window.py:2490-2534`. Zero exit code is never taken at face value.
10. **Error reporting — failed scans surface as "failed," partial results kept distinct** — `cli.py:241-305, 308-323`; `_any_failed`, per-manager ok/unsupported/failed outcomes.
11. **Test infrastructure** — `ScriptedExec` mock + `real_home` fixture (`tests/conftest.py:23-53`); suite never touches real user settings/history/Qt state.
12. **Concurrent per-manager execution with error isolation** — `_gather_per_manager` (`cli.py:97-110`); one dead manager cannot discard results from others.

## Implementation Order (Recommended)

Per the project's implementation-order rule (foundational first), the recommended order is:

1. **FIX-03** (`settings_store.py`) and **FIX-04** (`ignore_store.py`) — data-store locking; foundational shared-state safety.
2. **FIX-02** (`history_store.py`) — history JSONL locking; foundational shared-state safety.
3. **FIX-01** (`coordinator.py` PID-reuse race) — subprocess lifecycle; foundational before FIX-10.
4. **FIX-10** (`coordinator.py` kill fallback) — depends on FIX-01; both in `coordinator.py`.
5. **FIX-05** (`aur.py` off-by-one) — driver-level boundary fix.
6. **FIX-06** (`dnf.py` vendor-change swallow) — driver-level silent failure.
7. **FIX-07** (`pnpm.py` shim detection) — driver-level dependency drift.
8. **FIX-08** (`main_window.py` icon read) — UI-level silent failure.
9. **FIX-09** (`tui.py` kdeconnect) — UI-level silent failure.
10. **REF-01** — documentation only; no implementation required.

Tests for each task should be added alongside the fix, per project testing guidelines (`test_<area>.py`, `test_<behavior>` naming, mock subprocesses/package availability). After all fixes: run `QT_QPA_PLATFORM=offscreen python3 -m pytest tests -q` (expect 376 passed + new tests), run `ruff check` on `app/` + `run.py`, and confirm zero regressions before commit.
