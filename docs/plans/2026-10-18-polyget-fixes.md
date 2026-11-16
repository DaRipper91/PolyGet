# PolyGet: pacman partial-upgrade, lossy config stores, and false "up to date" scans

> **Implement task-by-task, in order.** Task 1 is the only HIGH item: `pacman -Sy <pkgs>` is emitted by the GUI upgrade paths and by `run.py upgrade -m pacman`, and a test currently enforces it. Do it first, and change `tests/test_sidebar_styles.py:171-178` in the same commit as the code. The breakage consequence comes from Arch documentation and was NOT executed (see Task 1).

**Context:** PolyGet is a PySide6 GUI, Textual TUI and headless CLI over 31 package-manager drivers. This pass (branch `CachyOS/BETA-FEATURES`, HEAD 99d9b35, 4 commits ahead of origin) re-verified the prior plans (`2026-07-20-*`, `2026-10-17-polyget-audit-fixes.md`, `2026-10-17-PolyGet-fixes.md`) against live code and hunted new bugs. FIX-05/06/08/09/10 and Tasks 4, 5, 7, 9, 11-16 of the older plans are fixed in live code and are NOT reopened here. Only the partial ones (Task 10, Task 15 residual) are. Already solid, so do not "fix" it: rescan-based upgrade verification, `DriverError`/`run_capture` with `ok_codes`, dnf `--refresh` and leaked-lock kill, fail-closed CLI pre-hooks, `version_scan` refuse-to-compare design, catalog `arch` vs `verified_on`, cleanup re-check before delete, notification quiet hours, sudo password via stdin (never argv), and the fail-closed pre-push hook. The driver registry is complete (31 modules, 31 classes, 41 catalog entries) and the suite is green at 647 passed.

**Repo rules that apply to every task:** `AGENTS.md` is protected (edit only when the owner asks). `CLAUDE.md`, `GEMINI.md` and `.cursorrules` are symlinks to it. Never push to `master` from a beta-only machine. Conflict hotspots between the two betas are `app/core/data/manager_catalog.yaml`, `app/core/manager.py`, `app/cli.py` and `README.md`. Tasks that touch them are marked **[HOTSPOT: peer sync]**. Sync with the peer machine before and after editing them. `.github/workflows/` and linter configs are protected by the owner's global ruleset and need explicit owner approval.

Labels: VERIFIED-EXEC means a reproduction was run. VERIFIED-READ means proven by reading code or grep. UNVERIFIED means reasoning only.

---

## Task 1 — pacman: stop emitting `-Sy <pkgs>` (partial upgrade) and lock the correct form in tests

**ID:** T1 · **Severity:** HIGH (documentation-based; consequence not executed) · **Hotspot:** none of the four; touches `pacman.py`, `tests/`.

**Problem:** `app/core/drivers/pacman.py:77` builds `["pkexec","pacman","-Sy","--noconfirm"] + packages`. `pacman.py:78` (no packages) correctly builds `-Syu`. `pacman.py:81` `get_sync_command` is a bare `pkexec pacman -Sy`. Commit c92a625 made the one-token `-S` to `-Sy` change and added `tests/test_sidebar_styles.py:171-178` (`test_pacman_selective_upgrade_includes_sync_flag`), which now asserts `-Sy`. Callers that pass a package list and reach `-Sy`: `main_window.py:4150`, `:4195`, `:4231` and `cli.py:405`. Executing `python run.py upgrade -m pacman` (no `--yes`) printed `pkexec pacman -Sy --noconfirm <~230 packages>`. So the default "upgrade everything outdated" CLI path is `-Sy` plus an explicit list, not `-Syu`. The TUI (`tui.py:467`, `:601`) passes no packages and gets `-Syu` (safe). `main_window.py:3920` (`_needs_admin`) also calls `get_upgrade_command(["pacman"])` as a dummy-name probe. It only inspects `cmd[0]`, never runs it, and is BENIGN but a smell. Same root cause, widened blast radius (stage 3 #11): after `run.py sync` or Ctrl+S "Sync repositories" (`-Sy`), catalog and driver installs (`pacman.py:129`, `manager_catalog.yaml` lines 36, 48, 62, 74, 87, 155, 194, 206: `pkexec pacman -S --noconfirm <pkg>`) run against a sync DB newer than the installed system.

**Honesty note:** the verified part is the emitted command line, the callers and the test lock-in. That `-Sy <subset>` and sync-then-install produce an unsupported partial-upgrade state (library bumps without dependents, kernel without matching modules) is reasoned from Arch's documented partial-upgrade policy. It was NOT executed. A disposable Arch container or VM would be needed to demonstrate it.

**Steps:**
1. Decide the contract with the owner. Recommended: pacman upgrades are all-or-nothing. `get_upgrade_command(packages)` returns `["pkexec","pacman","-Syu","--noconfirm"]` whether or not a subset is passed. A subset-only option is dropped for pacman (`-S` without `-y` against a possibly stale local DB is not safe either, because the checkupdates list is computed from a temp DB).
2. Edit `pacman.py:77` accordingly. Keep the docstring explaining why. Do not add `--ignore`-based subsetting without an explicit owner decision, since it recreates a partial upgrade.
3. Decide `get_sync_command` (`pacman.py:81`). Options: (a) return the full `-Syu` flow, (b) hide or disable "Sync repositories" for pacman and show an explanatory message, (c) keep `-Sy` but have the UI warn. Recommend (a) or (b). Update the callers behind `run.py sync` (`cli.py`, hotspot) and Ctrl+S only if the chosen option needs it.
4. In the GUI, when the user has unticked pacman packages, say that pacman upgrades the whole system. Check how `main_window.py:4150/4195/4231` build the list and surface this in the plan dialog. Do not change `_needs_admin`'s probe unless it is trivial.
5. Rewrite `tests/test_sidebar_styles.py:171-178`. It currently asserts `-Sy` and must be changed together with the fix. Assert the new contract: a package list yields `-Syu`, or whatever the owner decides, and never `-Sy` followed by names.
6. Add to `tests/test_pacman_driver.py`: for both `get_upgrade_command(["a","b"])` and `get_upgrade_command(None)`, `"-Sy"` is not in the argv unless it is `-Syu`. Add the same assertion for `get_sync_command()` per the decision in step 3.
7. Add a CLI test (`tests/test_cli.py`) that `upgrade -m pacman` with a mocked outdated list prints `-Syu`.

**Files to touch:** `app/core/drivers/pacman.py`, `tests/test_sidebar_styles.py`, `tests/test_pacman_driver.py`, `tests/test_cli.py`; maybe `app/ui/main_window.py`, `app/cli.py` **[HOTSPOT: peer sync]** if the sync command changes.

**Verify:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_pacman_driver.py tests/test_sidebar_styles.py tests/test_cli.py -q`, then `.venv/bin/python run.py upgrade -m pacman` (plan only, no `--yes`) and confirm the printed argv contains `-Syu`, not `-Sy <names>`.

---

## Task 2 — IgnoreStore and SettingsStore: atomic writes, no corrupt-as-empty, no stale-instance clobber

**ID:** T2 · **Severity:** MEDIUM · VERIFIED-EXEC

**Problem:** `app/core/ignore_store.py:25-28` `_load` swallows `JSONDecodeError` and returns `set()`. `:33-34` rewrites the whole file with `Path.write_text` (truncate then write, no temp file, no rename, no cross-process lock). `:11` holds only an in-process `threading.Lock`. `app/core/settings_store.py:27-34` `_load` does `except Exception: return self._defaults()`. `:121-124` `_save` is truncate-then-write. `:269-273` is a process-wide singleton, so a CLI run and a live GUI are separate stores. Measured: a reader loading while a writer rewrote a 3000-entry ignore file got a wrong or empty set in 184 of 397 loads (the next `add()` on that instance then wipes the user's ignore list). `SettingsStore` with a 3000-alias file and a writer loop: 177 of 300 fresh loads saw an EMPTY `alias_map`. Truncated JSON followed by one `set("ui.compact_mode", True)` rewrote the file with `alias_map: {}` (no warning, no backup). Two instances: `a.set(theme=latte)` then `b.set(accent=red)` reverted disk theme to `mocha`. Affected data: alias_map, skipped_versions, disabled_managers, hooks (a lost write silently drops a user's pre-upgrade snapshot hook), `dnf.allow_vendor_change`, `projects.dirs`. Real GUI exposure of lost updates is narrower than the harness: `IgnoreStore(` is constructed per call at `main_window.py:3343, :3712, :3791, :3836, :4023`, `tui.py:359`, `cli.py:250, :596` and `version_scan.py:436`. The torn-read wipe and non-atomic write do not depend on instance lifetime. The existing "FIX-03/FIX-04" locks serialize writes inside one process only.

**Steps:**
1. Add a small shared helper (e.g. `app/core/atomic_io.py`): `atomic_write_text(path, text)` writes to a temp file in the same directory, `flush` + `os.fsync`, then `os.replace(tmp, path)`. Create the parent directory. Clean the temp file on error.
2. Add a read-modify-write helper under a cross-process lock (`fcntl.flock` on a sibling `.lock` file) that re-reads the file before applying a change, so a stale instance cannot overwrite another process's edit. Linux-only is acceptable for now (repo targets Linux). Note that flock semantics over sshfs/NFS were NOT tested.
3. Change `_load` in both stores: on unreadable or invalid JSON, log it, move the bad file aside (e.g. `<name>.corrupt-<timestamp>`), and do not silently use empty data. Make sure a subsequent `save` cannot overwrite the only copy of a corrupt file without the backup. Missing file still means defaults.
4. Switch both `_save` methods to the helper. Keep the existing public API and the `threading.Lock`.
5. Optional, same helper: `history_store.py` stays append-only (see Task 3), and `blueprint.py:68` `return {}` on any exception can adopt the "do not treat corrupt as empty" rule (LOW).

**Files to touch:** new `app/core/atomic_io.py`; `app/core/ignore_store.py`; `app/core/settings_store.py`; tests below.

**Tests:** add real threaded and multiprocess tests (below, Task 3). Add unit tests: corrupt file is backed up and not treated as empty; two instances `a.add`, `b.add` both survive; `os.replace` is used (patch it to raise and assert the original file is untouched).

**Verify:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ignore_store.py tests/test_settings_store.py -q` (create `test_settings_store.py` if absent), then the full suite.

---

## Task 3 — Replace the vacuous lock tests with real contention tests

**ID:** T3 · **Severity:** MEDIUM (false assurance) · VERIFIED-EXEC

**Problem:** `tests/test_history_store.py:43-70` and `tests/test_ignore_store.py:23-61` use `asyncio.gather` over coroutines with no awaits, so they run sequentially on one thread and never contend. Mutation proof: replacing both `_save_lock`s with `contextlib.nullcontext()` left both tests passing. `AGENT_REPORT.md:9` claims "local JSONL concurrency lock assertions", which is false (zero lock assertions in either file). Separately, `history_store.py:35-37` opens the file and then takes the lock, and `record_removal` (`:58-60`) takes no lock. History appends are in practice safe via `O_APPEND`: real threads and fork processes (8x100 records, up to ~263 KB lines) gave 800/800 intact lines and `record_removal` gave 1600/1600. So the lock comment ("so concurrent GUI + CLI can't interleave") overstates what a `threading.Lock` does (LOW).

**Steps:**
1. `tests/test_history_store.py`: replace with `threading.Thread` workers (8 threads x 100 records, large payloads) and a `multiprocessing` variant (fork or spawn, 4 procs x 50). Assert N lines, every line valid JSON, no loss. Include `record_removal`.
2. `tests/test_ignore_store.py`: add threaded and multiprocess add/remove tests that assert no lost entries. These fail on today's code and pass after Task 2.
3. Prove the tests are real: temporarily swap the lock for `nullcontext` (or the old truncate-write) and confirm the relevant test fails. Do this by hand and note it in the commit message. Do not commit the mutation.
4. In `history_store.py`, take the lock before opening the file, give `record_removal` the same lock, and fix the comment to say it is an in-process guard and that cross-process safety comes from `O_APPEND` single `write()`.
5. Stage 4 #1 caveat: `history_store.py:31` and `:55` write `"verified": True` unconditionally, including the GUI "couldn't re-check" case. Either set it from the real verification result or document the field as "attempted". Pick one and test it.

**Files to touch:** `tests/test_history_store.py`, `tests/test_ignore_store.py`, `app/core/history_store.py`.

**Verify:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_history_store.py tests/test_ignore_store.py -q`, run 3 times to catch flakiness.

---

## Task 4 — pnpm and Yarn: a failed scan must not report "up to date"

**ID:** T4 · **Severity:** MEDIUM · VERIFIED-EXEC

**Problem:** `app/core/drivers/pnpm.py:79-87` (`_, stdout = await self._run(...)`, rc discarded, `json.loads(stdout or "{}")`) and `app/core/drivers/yarn.py:34-48` (rc discarded, non-JSON lines `continue`d). A fake `pnpm` or `yarn` exiting 1 with an error on stderr and empty stdout makes `check_updates()` return `[]` for both (reproduced with fake binaries on PATH). This contradicts the README design principle that a failed or hung check is never reported as up to date, and the README claim that drivers raise `DriverError` (these raise bare `RuntimeError` on exceptions and nothing on non-zero rc). Same class that older Tasks 4/5 fixed for pipx and Flatpak. Related: `pnpm.py:46-52` calls blocking `subprocess.run([path,"--version"], timeout=5.0)` inside `_needs_shell_fallback()`, reached from `async check_updates` (`:79`). `ScanWorker` runs all managers in one event loop (`main_window.py:109-133`), so this stalls every other scan for up to 5 s once per instance (LOW), and any completed run, even non-zero, counts as "no shim".

**Steps:**
1. Rewrite both `check_updates` on `run_capture` (`manager.py:37-63`) with an explicit `ok_codes`. `pnpm outdated` and `yarn outdated` exit 1 when updates exist, so read each tool's actual exit-code behavior from a real run or its docs and encode it. Treat spawn failure, timeout, or any other rc as `DriverError`.
2. Distinguish "empty stdout and rc ok" from "empty stdout and rc bad". Unparseable JSON on a success rc raises `DriverError` too.
3. Make the pnpm shim probe async (`asyncio.create_subprocess_exec`, or `asyncio.to_thread`), and fall back only on OSError or an explicit probe failure.
4. Also convert `dnf.py:144, :161` bare `RuntimeError` to `DriverError` if touched nearby (stage 4 noted it; optional).

**Files to touch:** `app/core/drivers/pnpm.py`, `app/core/drivers/yarn.py`, `tests/test_pnpm_driver.py`, `tests/test_yarn_driver.py` (create if absent).

**Tests:** failing rc with empty stdout raises `DriverError`; rc 1 with valid JSON (updates available) returns the list; malformed JSON raises; shim probe does not block the loop (assert via `asyncio.to_thread` mock).

**Verify:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_pnpm_driver.py tests/test_yarn_driver.py -q`, then repeat the fake-binary reproduction (`pnpm` exiting 1 on PATH) via `.venv/bin/python run.py outdated -m pnpm --json` and expect `"ok": false`.

---

## Task 5 — cpanm, Dart Pub, Hex, Julia, Poetry: report `unsupported` like Fisher instead of "0 updates, ok"

**ID:** T5 · **Severity:** MEDIUM · **[HOTSPOT: peer sync]** (README) · VERIFIED-EXEC for Dart Pub, VERIFIED-READ for the rest

**Problem:** `check_updates` is a hardcoded `return []` at `app/core/drivers/cpanm.py:51-55`, `dart_pub.py:53-58`, `hex.py:57-61`, `julia.py:54-58`, `poetry.py:61-62`. `python run.py outdated -m "Dart Pub" -m Fisher --json` gave Dart Pub `{"ok": true, "count": 0}` while Fisher (`fisher.py:45-46` raises `NotImplementedError`) correctly gives `"ok": false, "unsupported": true`. The handling already exists: `ScanWorker` `main_window.py:122-124`, `tui.py:344-349`, CLI. So the GUI, TUI and CLI show a green "up to date" for managers that never checked. `README.md:142` lists only Deno, Nix and Distrobox as unable to report outdated packages. `dart_pub.py:63` `get_upgrade_command()` with no packages builds `dart pub global activate` with no argument, which is meaningless. cpanm, hex, julia and poetry are not installed on the audit machine.

**Steps:**
1. Make the five `check_updates` raise `NotImplementedError` with a short reason, exactly as `fisher.py` does. If any can really be checked cheaply (e.g. `poetry show --outdated`), that is a separate feature, not part of this task.
2. Fix or guard each no-package `get_upgrade_command()` (`dart_pub.py:63` at minimum) so it does not emit a command that cannot work.
3. Update `README.md:142` to list all eight unsupported managers. Batch this edit with the other README fixes in Task 17 to limit hotspot churn.
4. Confirm the upgrade-verification path (`cli.py:162-199`, `main_window.py:4333-4376`) handles an unsupported manager sanely (a rescan that raises `NotImplementedError` should not mark an upgrade failed).

**Files to touch:** the five drivers; `tests/test_*_driver.py` for each; `README.md` (hotspot).

**Verify:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q -k "cpanm or dart or hex or julia or poetry or unsupported"`, then `.venv/bin/python run.py outdated -m "Dart Pub" --json` shows `"unsupported": true`.

---

## Task 6 — TUI does not run pre/post hooks

**ID:** T6 · **Severity:** MEDIUM · VERIFIED-READ (consequence reasoned) · **[HOTSPOT: peer sync]** if the shared code is extracted from `cli.py`

**Problem:** `grep -c -i hook app/ui/tui.py` returns 0. Hooks are wired only in `app/cli.py:141-153` (`_with_hooks`) and `app/ui/main_window.py:4181-4217, :4634-4678`. The TUI's `_upgrade_manager` (`tui.py:574+`) upgrades without them. `README.md:81-82` advertises pre/post hooks with no GUI-only caveat, and `README.md:46` lists the TUI as the front end for "SSH sessions and headless boxes". A user with a configured btrfs-snapshot pre-hook gets no snapshot when upgrading from the TUI. Nothing crashes. Severity settled at MEDIUM by the critic because impact needs a configured hook plus TUI use and was not exercised.

**Steps:**
1. Prefer extracting the hook-running logic from `cli.py:141-153` into `app/core/hooks.py` (which already stores hooks), and calling it from both CLI and TUI. If you touch `cli.py`, sync with the peer first. The smaller alternative is to import the helper from where it lives without moving it.
2. In `tui.py` wrap each upgrade and remove step: run pre-hooks first, abort that step and show the error if a pre-hook fails (fail-closed, as in the CLI), run post-hooks after. Preserve the existing sudo and `-Syu` flow.
3. If the owner prefers not to support hooks in the TUI, instead state this in `README.md:81-82` (batched in Task 17).

**Files to touch:** `app/ui/tui.py`, `app/core/hooks.py`, optionally `app/cli.py`; `tests/test_tui_upgrade.py`, `tests/test_hooks.py`.

**Tests:** mirror `tests/test_hooks.py::test_failed_pre_hook_stops_the_upgrade` for the TUI path: pre-hook failing means the upgrade command is never launched; successful hook means order is pre, upgrade, post.

**Verify:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_tui_upgrade.py tests/test_hooks.py tests/test_cli.py -q`.

---

## Task 7 — Driver discovery: one broken driver import must not take down all 31 managers

**ID:** T7 · **Severity:** MEDIUM (design risk) · **[HOTSPOT: peer sync]** only if `manager.py` is touched · VERIFIED-READ

**Problem:** `app/core/drivers/__init__.py:10-11` imports every driver module in an unguarded loop. One broken module (syntax error, missing optional import) aborts discovery for all managers. `manager.py:390` and `:410` now `logger.exception` then bare `raise` (older Task 2 fixed, correct to surface errors), but `except ImportError as e` leaves `e` unused (ruff F841 at both lines).

**Steps:**
1. Decide the policy with the owner. Recommended: isolate the failure per module, `logger.exception` it, record it in a module-level `FAILED_DRIVERS` list, and keep loading the rest. Surface the failures in `run.py managers` and the GUI's status or debug log so they are not silent. Do not return to swallowing, which older Task 2 removed.
2. If tests expect propagation, keep a strict mode (env var or parameter) that re-raises, so CI still fails on a broken driver.
3. Remove the unused `e` bindings at `manager.py:390, :410` (also closes 2 of the 17 ruff findings in Task 13).

**Files to touch:** `app/core/drivers/__init__.py`; `app/core/manager.py` **[HOTSPOT: peer sync]**; `tests/test_manager_discovery.py` (create if absent).

**Tests:** inject a module that raises `ImportError`; assert the other drivers still register and the failure is reported.

**Verify:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q -k "discover or registry"` and `.venv/bin/python run.py managers --json` (31 managers, all `available` fields unchanged).

---

## Task 8 — Unencoded user query in curl search URLs (cpanm, Dart Pub, Hex, Deno)

**ID:** T8 · **Severity:** LOW-MEDIUM · VERIFIED-EXEC for Dart Pub, VERIFIED-READ for the others

**Problem:** `app/core/drivers/cpanm.py:72`, `dart_pub.py:77`, `hex.py:79` build `f"...?q={query}"` and pass it to `curl -s`. `deno.py:71` only replaces `" "` with `%20`. Executed: `python run.py search "http client" -m "Dart Pub" --json` returned `"Dart Pub search failed: Expecting value: line 1 column 1 (char 0)"`. `search "{x}"` silently returned a result for `x` because curl treats `{}` as URL globbing. `&` or `#` truncate or inject URL parameters. `-s` without `-f` also hides HTTP errors. It is not shell injection (argv list), but it violates the AGENTS.md rule against constructing strings from user queries. Contrast `aur.py:83, :88` and `bun.py:73`, which use `quote()`.

**Steps:**
1. Use `urllib.parse.quote(query, safe="")` (or `urlencode`) in all four drivers.
2. Add `-g`/`--globoff` and `-f`/`--fail` to the curl argv, or move to `fetch_json` if the base class has it. Surface HTTP errors as `DriverError`.
3. Cover the pattern in a shared helper if it is repeated more than twice.

**Files to touch:** `app/core/drivers/cpanm.py`, `dart_pub.py`, `hex.py`, `deno.py`; their tests.

**Tests:** for queries `"http client"`, `"{x}"`, `"a&b#c"` assert the exact URL argument passed to the mocked subprocess is percent-encoded.

**Verify:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q -k "cpanm or dart or hex or deno"`, then `.venv/bin/python run.py search "http client" -m "Dart Pub" --json` returns results.

---

## Task 9 — GUI "configure NOPASSWD sudo" message can never succeed

**ID:** T9 · **Severity:** LOW-MEDIUM · VERIFIED-READ (live GUI path not executed)

**Problem:** `main_window.py:303-320` (message at `:310-314`) tells users to "configure NOPASSWD sudo". With NOPASSWD and no keyring password, `load_sudo_password()` returns `None`, and the code gives up and never runs `sudo` at all. The GUI can store no password (only the TUI can), though it can forget one (Settings, `main_window.py:3166-3180`, `_forget_sudo_password` at `:3584`).

**Steps:**
1. Either make the retry also try `sudo -n` (non-interactive, no password) when no password is stored, which actually serves NOPASSWD users, or change the message to state what can work (install or start a polkit agent; save a sudo password from the TUI).
2. Update `tests/test_execution_worker.py` for the chosen behavior.

**Files to touch:** `app/ui/main_window.py`, `tests/test_execution_worker.py`.

**Verify:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_execution_worker.py -q`.

---

## Task 10 — [UNVERIFIED] pkexec "not authorized" marker may trigger a sudo retry with the stored keyring password after a deliberate denial

**ID:** T10 · **Severity:** LOW-MEDIUM, capped (UNVERIFIED) · reasoning only. Partial remainder of older Task 10.

**Problem (as reasoned):** `main_window.py:204-209` `_PKEXEC_NO_AGENT_MARKERS` includes `"not authorized"`, retried at `:294-303` via `sudo -S` with `load_sudo_password()`, and duplicated at `tui.py:100-105`. pkexec prints "Error executing command as another user: Not authorized" when the user cancels or denies the dialog or policy refuses. If that is true, a deliberate denial is retried with sudo using the stored password without asking. Older Task 10's per-line matching is in place but does not address the marker itself. No real pkexec denial was exercised.

**Verify first, then fix:**
1. On a graphical session with a polkit agent, run a harmless pkexec command, click Cancel or deny, and record the exact stderr and exit code (126 vs 127 etc.). Repeat on a session with no agent. Save both outputs in the commit or PR.
2. Only if "Not authorized" really appears for a deliberate denial: remove or narrow the marker (e.g. require the no-agent wording), and add a test with the recorded denial text asserting no sudo retry. If it does not, close this task with the evidence.

**Files to touch:** `app/ui/main_window.py`, `app/ui/tui.py`, `tests/test_execution_worker.py`, `tests/test_tui_upgrade.py`.

**Verify:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_execution_worker.py tests/test_tui_upgrade.py -q`.

---

## Task 11 — [UNVERIFIED] Cancel and exit cannot stop a root-owned upgrade

**ID:** T11 · **Severity:** LOW-MEDIUM, capped (UNVERIFIED) · reasoning only

**Problem (as reasoned):** `app/core/coordinator.py:52-81` sends SIGTERM via `killpg`/`kill`; on `PermissionError` it only calls `_log`, with no user-visible message. `main_window.py:5619-5660` `closeEvent` says "Active tasks will be terminated", then falls back to `worker.terminate()` on QThreads (`:5658-5660`). pkexec re-execs the target as root, so a user-uid SIGTERM should get EPERM, and `pacman -Syu` would keep running after the window closes. There is no Cancel control for a running `ExecutionWorker` (`grep -n -i cancel` only hits dialogs at `:4112, :5085, :5458`). `QThread.terminate()` on a thread owning an asyncio loop is documented as unsafe. EPERM behavior was not exercised against a real root process. A trailing `except Exception: pass` remains at `coordinator.py:82` (LOW).

**Verify first, then fix:**
1. Start a long root child via pkexec (e.g. `pkexec sleep 600`) under `SubprocessCoordinator`, call `terminate_all()`, and record whether the signal is delivered or `PermissionError` occurs. Check the process afterwards.
2. If EPERM is confirmed: make `closeEvent` warn honestly that a privileged upgrade will continue, and surface the `PermissionError` in the UI. Prefer that over false "terminated" text. Do not add a kill-as-root mechanism without an owner decision.
3. Replace `QThread.terminate()` with cooperative shutdown if it is cheap. Otherwise leave and note.

**Files to touch:** `app/core/coordinator.py`, `app/ui/main_window.py`, `tests/test_coordinator.py`.

**Verify:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_coordinator.py -q`.

---

## Task 12 — [UNVERIFIED] dnf vendor-change gate is a substring on exact text

**ID:** T12 · **Severity:** LOW-MEDIUM, capped (UNVERIFIED) · no dnf on the audit machine

**Problem (as reasoned):** `app/core/drivers/dnf.py:70` `if "allow_vendor_change = 0" not in config: return updates`. If DNF5 or a future DNF prints the boolean as `false`/`False` or with different spacing, detection never fires and the "exit 0 but not upgraded" warning never appears. `tests/test_dnf_driver.py:181, :210` feed only the exact string `allow_vendor_change = 0\n`. `dnf --dump-main-config` is also not a DNF4 flag (DNF4 uses `dnf config-manager --dump`); the failure path logs and sets `vendor_change_detection_failed` (FIX-06, fixed).

**Verify first, then fix:**
1. On a Fedora machine (the Asahi box) with DNF4 and DNF5 if available, capture the real output of the config dump command(s) for `allow_vendor_change`. Save the samples.
2. Then parse with a tolerant regex (`allow_vendor_change\s*=\s*(0|false|no)`, case-insensitive) and add tests fed with the captured samples plus the old string. If the real output matches today's string, close with evidence and only widen the parser defensively.

**Files to touch:** `app/core/drivers/dnf.py`, `tests/test_dnf_driver.py`. Peer-machine action (Asahi) required for the evidence.

**Verify:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_dnf_driver.py -q`.

---

## Task 13 — Lint: decide on a real linter config or drop the "Lint passing" claim; clear the 17 findings

**ID:** T13 · **Severity:** LOW · VERIFIED-EXEC · **[HOTSPOT: peer sync]** (`manager.py`)

**Problem:** No `pyproject.toml`, `ruff.toml`, `setup.cfg`, `tox.ini`, `.flake8` or `.pre-commit-config.yaml` exists, and CI and the pre-push hook have no lint step. `AGENTS.md` says no linter is configured. `AGENT_REPORT.md` still claims "Lint passing", which cannot be falsified. External `ruff check --no-cache --isolated --select E9,F app run.py tests` gives 17 findings: 15 F401 unused imports and 2 F841 unused `e` at `manager.py:390, :410`. 4 are in `app/` (`main_window.py:12` `field`, `:2776` `debug_log`, `manager.py` x2) and 13 are in `tests/`. Zero syntax errors (E9) and zero undefined names (F821), so the code is clean in the bug-finding sense.

**Steps:**
1. Owner decision: (A) add a minimal `ruff.toml` (select E9, F; no formatter) and a CI lint step, which needs owner approval because linter configs, `.github/workflows/` and `AGENTS.md` are protected (AGENTS.md line "No repository-wide formatter or linter is configured" is changed only when the owner asks); or (B) keep no linter and remove the "Lint passing" line from the next `AGENT_REPORT.md`.
2. Either way, remove the 17 unused imports and bindings. Beware `main_window.py:12` and `:2776`: confirm nothing re-exports them or relies on side effects (grep for `main_window.field`/`main_window.debug_log` in tests before deleting).
3. If (A), run it with `--isolated` first in CI to avoid surprises.

**Files to touch:** `app/ui/main_window.py`, `app/core/manager.py` **[HOTSPOT: peer sync]**, 13 test files; `ruff.toml` + workflow only on option A.

**Verify:** `ruff check --no-cache --isolated --select E9,F app run.py tests` reports `All checks passed`, then `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q` still 647 passed (or more, after added tests).

---

## Task 14 — gem driver: test the retry path and stop orphaning grandchildren on timeout

**ID:** T14 · **Severity:** LOW (works) / MEDIUM for zero coverage of new branches · VERIFIED-EXEC

**Problem:** Commit 99d9b35 (unpushed, never through CI) added `--bulk-threshold 10`, a 180 s timeout, kill-on-timeout and a retry without the flag if stderr contains `bulk-threshold` (`app/core/drivers/gem.py:21-60`). `tests/test_gem_driver.py` was not touched. Mocked reproduction confirmed: rc 1 with "invalid option: --bulk-threshold" retries without the flag; an unrelated error does not retry; a first-call timeout kills and does not retry; a retry-call hang kills. But only the direct child is killed (no `start_new_session`/process-group kill): a `sleep 600` grandchild of a fake `gem` script survived as an orphan (low impact for real ruby `gem`). The two timeout blocks are duplicated, and `gem.py:44` `b"bulk-threshold" in stderr` is also hit by any error message that merely mentions the option. Installed `gem` 3.6.9 accepts the flag, so the fallback is mostly dead code on current RubyGems. The 0.6 s vs 31 s timing was a single run on one machine with zero outdated gems. Output equivalence on a non-empty outdated set was NOT checked.

**Steps:**
1. Add tests in `tests/test_gem_driver.py` mirroring the four mocked scenarios above (fallback, no retry on unrelated error, timeout kills and raises `DriverError`, retry timeout).
2. Spawn with `start_new_session=True` and kill the process group on timeout (reuse `SubprocessCoordinator` patterns). Add a test with a real fake-binary script that has a sleeping child.
3. Collapse the duplicated timeout/kill blocks into one helper. Narrow the fallback match to the unknown-option wording (e.g. "invalid option" and "bulk-threshold").
4. On a machine with at least one outdated gem, compare `gem outdated` and `gem outdated --bulk-threshold 10` output, and record it. Drop or soften the comment "~50-120s to ~20s" if it cannot be supported in-repo.

**Files to touch:** `app/core/drivers/gem.py`, `tests/test_gem_driver.py`.

**Verify:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_gem_driver.py -q`.

---

## Task 15 — Portability and CI: dependency bounds, `|| true`, Python matrix, unpushed commits never through CI

**ID:** T15 · **Severity:** LOW · VERIFIED-READ · `.github/workflows/tests.yml` is a protected file: needs explicit owner approval

**Problem:** `requirements.txt` has `keyring>=24.0` and `packaging>=23.0` with no upper bound (PySide6, rich and PyYAML are bounded; `textual==8.2.7` is exact). `.github/workflows/tests.yml` runs a Python 3.10/3.11/3.12 matrix only, while the dev machine runs 3.14. It also uses `pip install -r requirements-dev.txt 2>/dev/null || true`, which swallows a failed dev-deps install (a missing `pytest-asyncio` would then show up as confusing async test failures instead of an install error). The 4 unpushed commits (99d9b35, c92a625, 1a65394, ad315aa) have never been through CI. Earlier runs on 2026-10-18 failed and were fixed by a later commit, so the workflow is real. Also LOW (portability, untested): stores hardcode `~/.config` and `~/.local/share` (`settings_store.py:7`, `history_store.py:9`, `ignore_store.py:7`), ignoring `XDG_CONFIG_HOME`/`XDG_DATA_HOME`.

**Steps:**
1. Add upper bounds for `keyring` and `packaging` (next major, e.g. `keyring>=24.0,<26` and `packaging>=23.0,<27`; check current releases and the venv-installed versions first).
2. With owner approval, remove `2>/dev/null || true` from the dev install step, and add 3.13 and 3.14 to the matrix (or drop the 3.14 gap deliberately). Check the first run, since 3.10-3.12 compatibility was never exercised locally.
3. Process step, after Task 1: push the beta branch (never `master`) so the 4 commits plus the new work go through CI. Read `BRANCHING.md` before pushing. This is a push to `origin/CachyOS/BETA-FEATURES` only.
4. Optional: honor `XDG_CONFIG_HOME` and `XDG_DATA_HOME` in the three stores via one helper (can share Task 2's new module).

**Files to touch:** `requirements.txt`, `.github/workflows/tests.yml` (approval), optionally the three stores.

**Verify:** `.venv/bin/python -m pip install --dry-run -r requirements.txt -r requirements-dev.txt`, then `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q`, then confirm the GitHub Actions run is green on the pushed branch.

---

## Task 16 — Residual cross-ecosystem `rsplit("-", 1)` in `_parse_version_for` [UNVERIFIED impact]

**ID:** T16 · **Severity:** LOW (impact UNVERIFIED) · residual of older Task 15

**Problem:** `_parse_system_version` is fixed (`version_scan.py:196-200`, strips only a numeric pkgrel). Its sibling `_parse_version_for` at `version_scan.py:219-221` still does an unconditional `version.rsplit("-", 1)[0]` for cross-ecosystem system versions, dropping a `-rc1`-style suffix. Whether that produces a wrong comparison in practice was not tested.

**Steps:**
1. Write a failing test first in `tests/test_version_scan.py` with a `1.2.3-rc1` system version against a runtime version, and see if the result is actually wrong. If it is not, close with the test as documentation.
2. If wrong, reuse the numeric-pkgrel guard from `_parse_system_version`.

**Files to touch:** `app/core/version_scan.py`, `tests/test_version_scan.py`.

**Verify:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_version_scan.py -q`.

---

## Task 17 — Documentation drift (one batched pass; README is a hotspot)

**ID:** T17 · **Severity:** LOW · VERIFIED-READ · **[HOTSPOT: peer sync]** (README.md). `AGENTS.md` is protected: edit only if the owner asks.

**Problem and steps (each is a checkable edit):**
1. `README.md:17` badge "tests-491 passing" and `:346` "491 passed, 1 skipped in about 10 seconds" vs live 647 passed, 0 skipped, about 62 s. Update both, using the real numbers at the time of the edit.
2. `README.md:190` "All 19 subcommands" vs 22 in `app/cli.py:28-32` `COMMANDS`; the table at `:194-212` (19 rows) omits `clean`, `hooks`, `needs-restart`. Add the rows and fix the count.
3. `README.md:142` lists only Deno, Nix and Distrobox as unable to report outdated packages; add cpanm, Dart Pub, Hex, Julia and Poetry (do this together with Task 5).
4. `README.md:281` "coordinator.py # runs scans across managers" is wrong: `app/core/coordinator.py` is the `SubprocessCoordinator` PID registry and killer (`coordinator.py:12-95`).
5. `README.md:359-361` says `CLAUDE.md` covers design rules plus driver bugs that were fixed (Flatpak `-j`, Pipx fake PyPI lookup, Pacman exit code 1). `CLAUDE.md` is now a symlink to `AGENTS.md` (3385 bytes), which contains none of that. Reword the README sentence, or ask the owner whether to restore that content in `AGENTS.md`. `tests/test_pipx_driver.py:79` also cites "the actual CLAUDE.md 'fake PyPI lookup' bug".
6. `README.md:81-82` hooks bullet: add a TUI caveat only if Task 6 is declined.
7. `AGENTS.md:26-28` lists 12 commands (omits `remove`, `clean`, `hooks`, `needs-restart`, `system`, and others) and says only `upgrade`/`install`/`sync` need `--yes`, though `remove` and `clean` also gate on `--yes` (that detail was stated in the first pass and not re-executed). Owner-only edit. Propose the text in the PR, do not apply it unasked.
8. `ASAHI.md:16` says `python run.py system` does not exist on this branch; it does here (`run.py system` prints ARCH, DISTRO_FAMILY, PLATFORM). ASAHI.md is Asahi-machine guidance on the CachyOS branch. Coordinate with the Asahi machine and do not rewrite it from here.
9. `AGENT_REPORT.md:9` "local JSONL concurrency lock assertions" (false, see Task 3), "Lint passing" (unbacked, Task 13) and "Blocking Issues: None" (contradicted by Task 1): correct these in the next `AGENT_REPORT.md`, following the rename-to-`(OLD) AGENT_REPORT.md` rule. `(OLD) AGENT_REPORT.md` is a mandated filename, not a stray.
10. `docs/plans/2026-10-17-polyget-audit-fixes.md` still says "must remain 376 passed" (lines 54, 75, 95, 115, 137, 157, 179, 199, 220, 240) and the other plan's DoD says "402 passed". Both are stale. Do NOT edit those plan files from this task. If the owner wants them marked, add a one-line "superseded by 2026-10-18" note in a separate, explicitly approved commit.
11. Retracted, do not "fix": `README.md:108-109` "You can remove it from Settings" is accurate (the GUI has "Forget saved sudo password").

**Files to touch:** `README.md` (hotspot), later `AGENT_REPORT.md`; owner-gated: `AGENTS.md`, `ASAHI.md`, old plans.

**Verify:** `grep -n "491\|19 subcommands" README.md` returns nothing stale, and `grep -c "" README.md` sanity-check links; run `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q` to take the real count before writing it.

---

## Task 18 — DECISION FOR THE OWNER: public-repo exposure and tracked clutter (do not scrub automatically)

**ID:** T18 · **Severity:** LOW-MEDIUM overall · VERIFIED-READ · no credentials found (regex-only scan)

**Problem:** The repo is PUBLIC (`gh repo view` returned visibility PUBLIC). Tracked files expose topology and identity:
- Tailnet machine names `da-nvme` and `asahi`, sshfs mount layout, and the username and home path: `BRANCHING.md:27,77,95`; `ASAHI.md:33,37,64-68`; `docs/reports/ASAHI-READ-ONCE-2026-10-16.md:22,387-388,397,463,467,478`; `docs/reports/ASAHI-REVIEW-CANDIDATE-2026-10-17.md:3,39,128-165,188`; `scripts/peer-snapshot.sh:12,28-29,47` and `scripts/repo-check.sh:13,30-31` (defaults `PEER_USER=daripper`, `PEER_REPO=/home/daripper/Projects/PolyGet`); `scripts/review-export.sh:17,36`. Two historic plans embed `/home/daripper/Projects/PolyGet/...` file:// links (`docs/plans/2026-07-08-polyget-enhancements*.md`). No `.ts.net` FQDN, 100.x tailnet IP, or gmail string was found in tracked files; no hardcoded personal paths in `app/` or `run.py`.
- Git metadata (not tracked files): `theripper81791@gmail.com` on 71 commits and `daripper <daripper@example.com>` on 116.
- Tracked clutter: `codex_review.md` (its main finding, "requirements.txt lacks pytest", is stale), `RIP_IT_APART_FIXPLAN_2026-07-12.md` (cites `main_window.py:122-162`, which no longer matches), two root PDFs `2026-07-09-polyget-*.pdf` (about 360 KB, duplicates of docs/plans/*.md), and `docs/reports/` agent hand-off notes (internal cross-machine procedures).
- Fixed already, do not reopen: `.claude/skills/polyget/SKILL.md` path and `assets/polyget.desktop` placeholders.

**This is a decision for the owner, not an automatic cleanup.** Items to decide:
1. Is the topology exposure acceptable on a public repo, or should hostnames and paths become env-var defaults (`PEER_USER`, `PEER_REPO`, `PEER_HOST` from `.env` or arguments) and the report docs move to a private location?
2. Should the stale root clutter be `git rm`'d? Removal is a normal commit. Deleting project files needs the owner's confirmation. Purging history is a separate, destructive decision and is NOT proposed here.
3. The author-email exposure is inherent to git. Only a rewrite or a `noreply` address for future commits changes it. Rewriting is out of scope.
4. Run a real secret scanner (gitleaks or trufflehog) before declaring the repo clean. The stage-3 scan was grep/regex only (`git log --all -S'BEGIN OPENSSH'`, ghp_/AKIA/sk- patterns over all 221 commits, 0 hits). It does not rule out entropy-based or other token formats. Binary files and unreachable objects were not inspected.

**Files to touch (only after the decision):** the scripts above (`scripts/*.sh` also have shellcheck SC2087 and SC2164, LOW, not deeply reviewed), `BRANCHING.md`/`ASAHI.md` (coordinate with the peer machine), the clutter files.

**Verify:** `git grep -nI -E '/home/daripper|daripper|da-nvme|\.ts\.net|tailscale' -- . ':!.audit'` shows only the items the owner chose to keep.

---

## Task 19 — Cosmetic: silent-swallow cleanups

**ID:** T19 · **Severity:** LOW · VERIFIED-READ · **[HOTSPOT: peer sync]** if `manager.py` is touched

**Problem and steps:**
1. `app/ui/tui.py:357-362` `except Exception: pass` around `IgnoreStore().is_ignored(...)`: failure lets ignored or pinned packages into the upgrade-all set with no log line. Add one `_log` call.
2. `app/core/drivers/pacman.py:36-56`: if `checkupdates` exits 1 or raises, it falls through to `pacman -Qu` on the possibly stale local DB and reports "up to date" or a stale list with no log. Log the fallback, and consider marking the result as "from stale DB".
3. `app/ui/tui.py:562-566`: the per-device `kdeconnect` `create_subprocess_exec(... --ping-msg ...)` is never awaited or waited, leaving unreaped children. Await `wait()` with a short timeout.
4. `app/core/coordinator.py:82` trailing `except Exception: pass`: log it.
5. `app/core/blueprint.py:68` `return {}` on any exception makes an invalid blueprint indistinguishable from an empty one: log and surface.
6. Test noise: `RuntimeWarning: coroutine 'AsyncMockMixin._execute_mock_call' was never awaited` at `tui.py:632/634` and `yarn.py:28` (tests mock `kill`/`stdin` as async while the code calls them sync). Switch those mocks to `MagicMock`. Harmless.
7. `main_window.py:5405` `self._held_failures & set(self.scan_errors) or self._held_failures` announces stale held failures when all have recovered (noted in stage 4 #9, no test seen). Fix only if cheap.

**Verify:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q -W error::RuntimeWarning` should show fewer warnings than the 28 baseline; full suite still green.

---

## Suggested execution order

1. **T1** (HIGH) first, alone, with its test change in the same commit.
2. **T15 step 3**: push `CachyOS/BETA-FEATURES` (never `master`) so the 4 unpushed commits plus T1 go through CI before more piles on.
3. **T2 then T3** (store atomicity first, then tests that exercise it).
4. **T4, T5, T8** (driver-only changes; no hotspot except README, deferred).
5. **T6, T7, T9** (TUI hooks, discovery isolation, NOPASSWD message).
6. **T14, T13, T19, T16** (gem, lint, swallows, version_scan residual).
7. **Peer sync, then one batched edit of the hotspot files** (`manager.py` bits from T7/T13/T19, `cli.py` from T1/T6 if any, `README.md` from T5/T6/T17). Sync with the peer machine before and after.
8. **T15 steps 1, 2, 4** (needs owner approval for the workflow), and **T17** doc pass.
9. **T10, T11, T12** (UNVERIFIED): only after real-hardware evidence is collected; they can run in parallel with anything above because they need machine time, not code.
10. **T18**: owner decision at any time. Nothing else depends on it.

Hotspot summary: T5 (README), T6 (cli.py if extracted), T7 (manager.py), T13 (manager.py), T17 (README), T19 (manager.py), plus T1 if `cli.py` changes for `sync`. No task touches `manager_catalog.yaml` (T1 cites its pacman lines as evidence only). Never push to `master`.

---

## Known coverage gaps

Copied from the critic pass. This plan does not claim these areas are clean. "Not looked at" is not "clean".
- `app/ui/main_window.py` (5660 lines, the biggest hotspot): only roughly lines 83-335, 502-615, 3920, 4112-4440 (partial), 5331-5414, 5480-5504 and 5619-5660 were read. Store, search, blueprint and repos pages, slot thread-safety and the rest were not examined.
- `app/cli.py` (951 lines): read only around `:125-225` and `:405`; `clean`, `remove`, `repos` and `hooks` bodies unread. `app/ui/tui.py` (805 lines): read only around `:100`, `:344-362`, `:467`, `:552-640`, `:706`.
- `app/core/version_scan.py`: examined at `:27-129, :141-162, :194-259, :282-284`; the rest (473 lines) unread, though 523 lines of tests pass.
- `manager_catalog.yaml` (472 lines): checked only by grep (sudo/pkexec/curl) and a registry diff; per-distro command correctness not read. About 25 other drivers were scanned only by a returncode-helper grep and an AST swallow scan. `apt.py` was not discussed.
- `sudo_secret.py`, `settings_store.py` beyond `:27-34/:121-124`, coordinator internals, janitor, blueprint, `scripts/*.sh` logic (`rm -rf` in `review-export.sh:61,96,106`, rsync `--delete` in `peer-snapshot.sh:64`), `ASAHI.md` body and `docs/reports` bodies: not reviewed.
- Not executed anywhere: any real pkexec/sudo/polkit flow, real pacman/dnf/apt flows, Fedora and Asahi paths, Python 3.10-3.12, network filesystems (sshfs/NFS lock semantics), `gitleaks`/`trufflehog`/`pip-audit`. The secret scan is regex-only, and "no secrets found" must not be read as "clean".
- The pacman partial-upgrade consequence was reasoned from Arch documentation and not executed.
- UNVERIFIED items: T10, T11, T12 (stage 3 #6, #7, #8) and the impact in T16.
- Unpushed commits 99d9b35, c92a625, 1a65394, ad315aa have never been through CI.

---

## Definition of done

- **Baseline now:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` gives 647 collected / 647 passed, 0 failed, 0 skipped, about 62 s. The final count must be 647 plus the tests added by this plan, with 0 failed.
- **T1:** no `-Sy <names>` form appears in `pacman.py`; `tests/test_sidebar_styles.py:171-178` asserts the new contract; `run.py upgrade -m pacman` prints `-Syu`; the owner's decision on `get_sync_command` is recorded in the commit message.
- **T2/T3:** both stores write via temp file + `os.replace`; a corrupt file is backed up and never treated as empty; threaded and multiprocess tests in `tests/test_history_store.py` and `tests/test_ignore_store.py` fail when the lock or atomic write is removed (mutation checked once by hand).
- **T4:** fake failing `pnpm`/`yarn` give `"ok": false`; the pnpm shim probe no longer blocks the loop.
- **T5:** `run.py outdated -m "Dart Pub" --json` (and the other four) shows `"unsupported": true`.
- **T6:** a TUI upgrade with a failing pre-hook never launches the upgrade; tests prove it.
- **T7:** an injected broken driver module is reported but the other managers still load.
- **T8:** exact encoded URL asserted for `"http client"`, `"{x}"`, `"a&b#c"` in all four drivers.
- **T9:** NOPASSWD message matches actual behavior.
- **T10-T12:** each is either closed with captured real-hardware evidence or fixed with a test built from that evidence. None may be reported as a confirmed bug without it.
- **T13:** `ruff check --no-cache --isolated --select E9,F app run.py tests` goes from the 17-finding baseline (15 F401, 2 F841) to 0; the owner has decided on a config vs removing the "Lint passing" claim.
- **T14:** gem retry, no-retry, and timeout-kill paths are tested; process-group kill leaves no orphaned grandchild in the fake-binary test.
- **T15:** `keyring` and `packaging` are bounded; the beta branch has a green CI run covering the 4 formerly unpushed commits (workflow edits only with owner approval).
- **T16:** a test documents the `-rc1` behavior; fixed or closed with evidence.
- **T17:** README numbers and command counts match live values (647 / 22 commands); nothing in protected files (`AGENTS.md`, old plans) was edited without the owner asking.
- **T18:** the owner's decision is recorded; if a scan is wanted, a real scanner was run.
- **T19:** the listed swallows log; the warning count is lower than the 28 baseline.
- **Repo rules:** no push to `master`; hotspot files were synced with the peer machine before and after editing; `AGENT_REPORT.md` updated per the rename rule and with honest build/lint/test status.
