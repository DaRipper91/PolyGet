# Rip-It-Apart Fix Plan (2026-07-12)

## 1. Top Priority: NPM Driver Update Loop (UX/Semver Mismatch)
**Severity:** High
**File:** `app/core/drivers/npm.py`
**Lines:** 78-85, 87-118

**Finding:** The NPM driver queries `npm outdated -g --json`, which returns both `wanted` (the max version permitted by semver constraints) and `latest` (the absolute newest version). `npm.py` extracts `info.get("latest")` for the UI. However, the update command returned by `get_upgrade_command()` is `npm update -g`, which respects semver and only upgrades to the `wanted` version. If `wanted` is less than `latest`, the UI claims an update is available but PolyGet's update operation won't install it, creating an infinite loop where the package always appears outdated.

**Resolution Plan:**
Instead of `npm update -g` (which limits updates), change `get_upgrade_command` to explicitly use `npm install -g <package>@latest` when specific packages are passed, or iterate and install latest for all. Alternatively, if honoring semver is the strict intent, change `check_updates` to read `info.get("wanted")` and only surface the package as outdated if `wanted > current`. Given PolyGet's design as a system updater, upgrading to `latest` is usually the expected behavior.

## 2. Sudo Upgrade Process Is Never Tracked for Cleanup (Textual TUI)
**Severity:** Medium
**Files:** `app/ui/tui.py` (lines 336-386, esp. 355-373), `app/core/coordinator.py` (lines 27-31, 43-69), `app/ui/main_window.py` (lines 138-155)

**Finding:** The original write-up of this issue ("coordinator can't kill sudo process groups without elevated privileges") was traced end-to-end and doesn't hold up — `coordinator.py`'s `PermissionError → os.kill()` fallback (lines 56-62) is never even reached for a sudo upgrade, because it's dead code on that path:

- `SubprocessCoordinator.register()` has exactly one caller in the whole app: `app/ui/main_window.py:145`, inside `ExecutionWorker.run()` — the **Qt UI's** generic command runner, which spawns its subprocess with `preexec_fn=os.setsid` (line 142) and registers the resulting pid.
- The actual sudo-elevated upgrade path is `app/ui/tui.py:_upgrade_manager()` (lines 336-386), which belongs to the **separate Textual-based UI** launched via `python run.py --tui` (selected in `app/main.py:10-14` — this is a live, dual-UI codebase, not dead code). That method spawns its subprocess directly (line 363) with no `preexec_fn=os.setsid`/`start_new_session=True` and never imports or references `SubprocessCoordinator` at all.

So there are two compounding gaps, not one: (a) the sudo child is never registered, so `coordinator.terminate_all()` has no idea it exists; and (b) even if it were registered, it wasn't given its own process group, so `os.killpg()` would have nothing group-shaped to target. If PolyGet is force-closed mid-upgrade while running in `--tui` mode, the root-owned `sudo`/package-manager process is simply never signaled by anything — it's not that permission is denied, it's that no cleanup attempt is ever made.

**Resolution Plan:**
1. In `tui.py:_upgrade_manager()`, spawn the subprocess with `start_new_session=True` (equivalent to `preexec_fn=os.setsid` for `create_subprocess_exec`) and call `SubprocessCoordinator().register(proc.pid)` / `.unregister(proc.pid)` around the run, mirroring `ExecutionWorker.run()` in `main_window.py`.
2. Wire the Textual app's shutdown/quit handling to call `SubprocessCoordinator().terminate_all()`, the same way `main_window.py:2062` does on Qt close.
3. Once both UIs actually register their sudo children, revisit whether `coordinator.py`'s existing `PermissionError → os.kill()` fallback is sufficient, or whether a `sudo -n kill` escalation is needed for cases where `os.killpg`/`os.kill` can't reach a root-owned group at all (e.g. `pkexec`-elevated DNF/Pacman commands, which run as a *different* uid than the PolyGet process and won't be signalable by a plain `os.kill` regardless of process-group setup).

## 3. Qt UI Has No Sudo Password Channel — `ExecutionWorker` Will Stall on npm's Sudo Fallback
**Severity:** Medium
**Files:** `app/ui/main_window.py` (lines 122-162, `ExecutionWorker`), `app/core/drivers/npm.py` (lines 104-118)

**Finding:** `npm.py:get_upgrade_command()` can return a bare `["sudo", "npm", "update", "-g", ...]` when the global npm prefix isn't user-writable (lines 110 and 116). Unlike the `pkexec`-based commands used by `dnf.py:80-88` and `pacman.py:41-43` (which pop their own polkit auth dialog and need no stdin from the caller), plain `sudo` needs either a cached credential or a password written to its stdin.

The Qt UI's `ExecutionWorker` (`main_window.py:122-162`) is the only place that runs `get_upgrade_command()` output on that UI, and it does not special-case `sudo`: it neither adds `-S` nor opens `stdin=PIPE` (it only pipes `stdout`/`stderr`, line 138-142) nor has any password-prompt UI equivalent to `tui.py`'s `PasswordModal` (`tui.py:49`, used at `tui.py:395-403`). If a user is on a system where `npm`'s global prefix isn't writable and runs the Qt (default, non-`--tui`) build, clicking "upgrade" for NPM will spawn a `sudo` process that blocks waiting for a password it can never receive, hanging that upgrade indefinitely with no feedback to the user beyond a stalled log.

**Resolution Plan:**
Either (a) give `ExecutionWorker` the same sudo-awareness `tui.py` already has — detect `cmd[0] == "sudo"`, open `stdin=PIPE`, and prompt via a Qt password dialog before writing to stdin — or (b) change `npm.py`'s fallback (lines 104-118) to return a `pkexec` command instead of `sudo`, matching the pattern already used by `dnf.py`/`pacman.py`, which needs no stdin handling from either UI. (b) is the smaller, lower-risk change and keeps sudo-handling logic in one place (`tui.py`) instead of duplicating a password dialog into the Qt UI.
