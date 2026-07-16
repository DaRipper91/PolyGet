# PolyGet: Features and Improvements — Post Batch-Upgrade-Failure Fix

> **For Antigravity:** This plan assumes `30a12f0` (npm update-loop / sudo-stall fix) and the
> follow-up commit `6b831c0` (batch-upgrade queue now surfaces per-manager failures instead of
> always reporting "Complete") have already landed. Several tasks below build directly on the
> failure-tracking pattern `handle_queue_worker_finished` now uses — read that function
> (`app/ui/main_window.py`) before starting Task 6.

**Goal:** Close the gaps found while investigating why a batch npm upgrade silently didn't apply:
lack of failure visibility (fixed), lack of package-level control (pin/ignore), lack of any
persistent record of what happened, and a few structural rough edges in the queue/driver code that
make bugs like the one just fixed more likely to recur elsewhere.

**Sequencing:** Tasks 6, 7, and 10 touch the same queue machinery — do them together, in order, in
one pass. Tasks 1–5 (new features) are independent of each other and of the improvements block.
Task 4 (apt driver) has no dependency on anything else and is the best standalone starting point if
picking one thing to ship first.

---

## 1. Package Pin/Ignore List

**Problem:** `handle_scan_results` (`app/ui/main_window.py:1508-1520`) unconditionally adds every
outdated package to `self.selected_updates[manager_name]`. There is no way to permanently exclude
a package (e.g. "never auto-select this major bump") — the user must remember to uncheck it on
every single scan.

**Files:**
- Create `app/core/ignore_store.py`
- Modify: `app/ui/main_window.py` (`handle_scan_results`, `rebuild_updates_list`, item context menu)

**Design:**
```python
"""Persisted per-package ignore list, keyed by manager name + package name."""

import json
from pathlib import Path

_IGNORE_PATH = Path.home() / ".config" / "polyget" / "ignored_packages.json"


class IgnoreStore:
    """Simple JSON-backed set of (manager_name, package_name) pairs to exclude from auto-select."""

    def __init__(self, path: Path = _IGNORE_PATH) -> None:
        self._path = path
        self._entries: set[tuple[str, str]] = self._load()

    def _load(self) -> set[tuple[str, str]]:
        if not self._path.exists():
            return set()
        try:
            data = json.loads(self._path.read_text())
            return {(item["manager"], item["package"]) for item in data}
        except Exception:
            return set()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = [{"manager": m, "package": p} for m, p in sorted(self._entries)]
        self._path.write_text(json.dumps(payload, indent=2))

    def is_ignored(self, manager_name: str, package_name: str) -> bool:
        return (manager_name, package_name) in self._entries

    def add(self, manager_name: str, package_name: str) -> None:
        self._entries.add((manager_name, package_name))
        self._save()

    def remove(self, manager_name: str, package_name: str) -> None:
        self._entries.discard((manager_name, package_name))
        self._save()
```

**Wiring into `main_window.py`:**
- In `handle_scan_results`, skip auto-adding to `selected_updates` when `IgnoreStore().is_ignored(manager_name, pkg["name"])`; still show the row, just unchecked and visually muted.
- Add a right-click context menu action "Ignore this update" on updates-list rows that calls `IgnoreStore().add(...)` and immediately unchecks + re-renders that row.
- Add a small "Manage Ignored Packages" dialog (simple `QListWidget` with a remove button) reachable from the dashboard toolbar — reuses `IgnoreStore().remove(...)`.

**Tests:** `tests/test_ignore_store.py` — round-trip add/remove/persist against a temp path (don't touch the real `~/.config`).

---

## 2. Security Audit Surface

**Problem:** Several drivers already wrap tools with a native vulnerability-audit subcommand (`npm audit --json`, `cargo audit --json` via cargo-audit if installed, `pip-audit` for Pipx-managed tools, `gem audit` via bundler-audit). None of it is surfaced. PolyGet currently only tells you a package is *outdated*, never that it's *vulnerable*.

**Files:**
- Modify: `app/core/manager.py` (base class — add optional hook)
- Modify: `app/core/drivers/npm.py`, `app/core/drivers/cargo.py`, `app/core/drivers/pipx.py`
- Modify: `app/ui/main_window.py` (badge/column on the updates list)

**Design — base class addition (opt-in, not required):**
```python
async def check_vulnerabilities(self) -> list[dict[str, Any]]:
    """Optionally report known-vulnerable installed packages.

    Returns:
        list[dict[str, Any]]: Each dict has at least 'name', 'severity', 'advisory'.
        Base implementation returns [] — override only where a real audit tool exists.
    """
    return []
```

**npm.py addition:**
```python
async def check_vulnerabilities(self) -> list[dict[str, Any]]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "npm", "audit", "-g", "--json",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        import json
        data = json.loads(stdout.decode(errors="ignore") or "{}")
        results = []
        for name, info in data.get("vulnerabilities", {}).items():
            results.append({
                "name": name,
                "severity": info.get("severity", "unknown"),
                "advisory": (info.get("via") or [{}])[0].get("title", "") if isinstance(info.get("via"), list) else "",
            })
        return results
    except Exception:
        return []
```
Note: `npm audit -g` is a genuinely different (and slower, network-bound) call than `npm outdated -g` — run it lazily (a separate "Check Vulnerabilities" action), not on every scan, to avoid regressing scan latency.

**UI:** Add a shield icon column on rows where `check_vulnerabilities()` reports a hit, with severity in the tooltip. Cargo/Pipx audits are conditional on `cargo-audit`/`pip-audit` actually being installed (`shutil.which`) — degrade to an empty result silently, same pattern as every other optional-tool check in this codebase (see `check_updates` fallbacks).

**Tests:** Mock-based, mirroring `tests/test_npm_driver.py`'s `AsyncMock` pattern — assert JSON parsing produces the right severity/name pairs and that a missing `cargo-audit` binary yields `[]` without raising.

---

## 3. Update History Log

**Problem:** Nothing persists what was upgraded, when, or from/to which version. After the failure-surfacing fix in Task 6/already-shipped work, users can *see* a failure, but there's no record to look back at later ("did npm actually get updated last Tuesday").

**Files:**
- Create `app/core/history_store.py`
- Modify: `app/ui/main_window.py` (`handle_queue_worker_finished`, new "History" nav tab)

**Design:**
```python
"""Append-only JSON Lines log of upgrade attempts, one record per manager per batch."""

import json
import time
from pathlib import Path
from typing import Any

_HISTORY_PATH = Path.home() / ".local" / "share" / "polyget" / "history.jsonl"


def record_upgrade(manager_name: str, packages: list[str], success: bool, path: Path = _HISTORY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": time.time(),
        "manager": manager_name,
        "packages": packages,
        "success": success,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def load_history(path: Path = _HISTORY_PATH, limit: int = 200) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    records = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return list(reversed(records))
```

**Wiring:** Call `record_upgrade(manager_name, packages, success)` from `handle_queue_worker_finished` — it already has `success` and `manager.name` in scope after Task 6/the shipped fix; thread `packages` through from `run_next_upgrade_queue`'s pop. Add a "History" item to `nav_list` backed by a read-only table populated from `load_history()`.

**Tests:** `tests/test_history_store.py` — write N records to a temp path, assert `load_history` returns them newest-first and respects `limit`.

---

## 4. `apt` Driver (Debian/Ubuntu System Package Manager)

**Problem:** PolyGet has full System-category drivers for DNF and Pacman but nothing for the
Debian/Ubuntu family, despite `app/core/distro.py` already recognizing `debian`/`ubuntu` as a
family (used today only for `manager_catalog.yaml` `self_install` blocks, e.g. Bundler's Debian
install command). This is the single largest gap in distro coverage relative to actual Linux
desktop market share.

**Files:** Create `app/core/drivers/apt.py`, `tests/test_apt_driver.py`; modify `app/core/data/manager_catalog.yaml`

**Design (mirrors `dnf.py`'s shape, adapted for apt's actual CLI):**
```python
import asyncio
import shutil
from typing import Any
from app.core.manager import PackageManager, register_manager


@register_manager
class AptManager(PackageManager):
    """Package manager driver for APT (Debian/Ubuntu)."""

    name: str = "APT"
    category: str = "System"

    def is_available(self) -> bool:
        return shutil.which("apt-get") is not None

    async def check_updates(self) -> list[dict[str, Any]]:
        # apt-get has no stable JSON output; `apt list --upgradable` is the
        # documented-stable machine-readable-ish form. Format per line:
        # "pkgname/repo,repo version arch [upgradable from: oldversion]"
        try:
            proc = await asyncio.create_subprocess_exec(
                "apt", "list", "--upgradable",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            updates = []
            for line in stdout.decode(errors="ignore").splitlines():
                if "/" not in line or "upgradable from" not in line:
                    continue
                name = line.split("/", 1)[0].strip()
                parts = line.split()
                new_ver = parts[1] if len(parts) > 1 else "Unknown"
                current = line.split("upgradable from:", 1)[-1].strip().rstrip("]")
                updates.append({"name": name, "current": current or "Installed", "new": new_ver})
            return updates
        except Exception:
            return []

    def get_upgrade_command(self, packages: list[str] = None) -> list[str]:
        if packages:
            return ["pkexec", "apt-get", "install", "--only-upgrade", "-y"] + packages
        return ["pkexec", "apt-get", "upgrade", "-y"]

    def get_sync_command(self) -> list[str] | None:
        return ["pkexec", "apt-get", "update"]

    async def list_installed(self) -> list[str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "apt-mark", "showmanual",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            return [line.strip() for line in stdout.decode(errors="ignore").splitlines() if line.strip()]
        except Exception:
            return []

    def get_install_command(self, package: str) -> list[str]:
        return ["pkexec", "apt-get", "install", "-y", package]

    supports_repos: bool = True

    async def list_repos(self) -> list[dict[str, Any]]:
        # Parses /etc/apt/sources.list + /etc/apt/sources.list.d/*.list directly —
        # apt has no `repolist`-equivalent CLI command the way dnf does.
        import glob
        repos = []
        sources = ["/etc/apt/sources.list"] + glob.glob("/etc/apt/sources.list.d/*.list")
        for path in sources:
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        enabled = line.startswith("deb ") or line.startswith("deb-src ")
                        if not enabled and not line.startswith("# deb"):
                            continue
                        raw = line.lstrip("# ").strip()
                        repos.append({"id": raw, "name": raw, "url": raw, "enabled": enabled})
            except OSError:
                continue
        return repos

    def get_add_repo_command(self, repo_url_or_id: str) -> list[str]:
        return ["pkexec", "add-apt-repository", "-y", repo_url_or_id]

    def get_remove_repo_command(self, repo_id: str) -> list[str]:
        return ["pkexec", "add-apt-repository", "--remove", "-y", repo_id]

    async def search_packages(self, query: str) -> list[dict[str, Any]]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "apt-cache", "search", query,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=12.0)
            results = []
            for line in stdout.decode(errors="ignore").splitlines():
                if " - " not in line:
                    continue
                name, desc = line.split(" - ", 1)
                results.append({"name": name.strip(), "id": name.strip(), "description": desc.strip(), "version": ""})
            return results
        except Exception:
            return []
```

**Catalog entry** (`manager_catalog.yaml`, following the existing `dnf`/`pacman` shape):
```yaml
- id: apt
  name: APT
  category: System
  description: Debian/Ubuntu system package manager.
  icon: package-x-generic
  binary: apt-get
  has_driver: true
  self_install: {}
```

**Cloud-environment note:** unlike DNF/Pacman, apt *is* available in the Ubuntu-based Claude Code cloud environment per `CLAUDE.md` — this driver can be fully tested there, not just on real hardware. Prioritize writing the test suite to actually exercise `apt list --upgradable` parsing against captured real output, not just mocks.

**Tests:** `tests/test_apt_driver.py`, mirroring `tests/test_npm_driver.py`'s `AsyncMock` structure — one fixture per representative `apt list --upgradable` line format, plus a `list_repos()` test against a temp `sources.list` file.

---

## 5. System Tray + Background Scan

**Problem:** No `QSystemTrayIcon` exists anywhere in `app/ui/main_window.py`. PolyGet only tells you about updates while it's open and foregrounded — for a tool whose whole pitch is "one dashboard for everything," that's a real gap versus e.g. `dnfdragora`/`pamac`'s tray-based update notifiers.

**Files:** Modify `app/ui/main_window.py` (`MainWindow.__init__`, `closeEvent`)

**Design:**
- Add a `QSystemTrayIcon` in `MainWindow.__init__`, built from the same icon set already used for the window (`system-software-update`, matching the `.desktop` file's `Icon=`).
- Add a `QTimer` (default interval: configurable, start at 4 hours) that calls `scan_all()` in the background; on completion, if `sum(len(u) for u in self.updates_cache.values()) > 0`, update the tray tooltip/badge and optionally fire a `tray_icon.showMessage(...)` notification.
- Override `closeEvent` (already exists, currently handles active-PID confirmation — extend, don't replace) so the window close button minimizes to tray instead of quitting, with quit only reachable from the tray context menu's explicit "Quit" action. Keep the existing active-process confirmation dialog intact for the real quit path.
- Tray context menu: "Open PolyGet", "Scan Now", "Quit".

**Design decision to flag for the user before building:** background scanning on a timer means periodically shelling out to every installed manager's outdated-check even when the window is closed — for network-bound checks (npm, cargo, pipx all hit registries) this has a real bandwidth/rate-limit cost multiplied by however many managers are installed. Recommend defaulting the timer to a conservative interval (4+ hours) and making it user-configurable rather than fixed, and skipping the background scan entirely if `check_vulnerabilities`-style network calls are added later (Task 2) — those should stay manual-trigger-only.

**Tests:** Tray icon construction under `QT_QPA_PLATFORM=offscreen` (existing test convention for this repo) — assert the tray icon exists and the timer is configured, not a full behavioral test (Qt timers are awkward to test meaningfully; keep this to construction/wiring assertions).

---

## 6. Batch-Upgrade Retry Action

**Problem:** The just-shipped failure dialog (`run_next_upgrade_queue`, commit `6b831c0`) tells the user which managers failed but offers no way to retry them — the user has to go back to the dashboard, reselect the same packages, and re-run the whole batch.

**Files:** Modify `app/ui/main_window.py` (`run_next_upgrade_queue`)

**Design:** Track failures as `(manager, packages)` tuples, not just names, so they can be re-queued directly:
```python
# In handle_queue_worker_finished, alongside the existing self.upgrade_failures.append(manager_name):
self.upgrade_failed_items.append((manager, packages))
```
Add `self.upgrade_failed_items: list[tuple[PackageManager, list[str]]] = []`, cleared in `start_batch_upgrade` alongside `upgrade_failures`. In the `QMessageBox.warning` branch, replace the plain warning with a `QMessageBox` that has a custom "Retry Failed" button; wire it to `self.upgrade_queue.extend(self.upgrade_failed_items)` followed by `self.run_next_upgrade_queue()` instead of falling through to `scan_all()`.

---

## 7. Audit `handle_sync_worker_finished` / `handle_blueprint_sync_worker_finished` for the Same Silent-Success Pattern

**Problem:** The bug just fixed in `handle_queue_worker_finished` (`success` parameter discarded, final dialog always claims completion) has two siblings:
- `handle_sync_worker_finished` (`app/ui/main_window.py:1804-1810`) — logs success/failure per item correctly, but `run_next_sync_queue`'s terminal state (`app/ui/main_window.py:1785-1792`) always shows `"Sync Complete"` / `"All repository metadata has been refreshed."` regardless of any per-item failure.
- `handle_blueprint_sync_worker_finished` (`app/ui/main_window.py:2039-2044`) — same pattern: logs correctly, but `run_next_blueprint_sync`'s terminal state (`app/ui/main_window.py:2015-2027`) always says `"Sync Complete"` / `"All missing blueprint packages have been installed."` regardless of failures.

**Files:** Modify `app/ui/main_window.py`

**Resolution:** Apply the exact same pattern used in Task-6's fix (and already shipped for the main upgrade queue) to both: add a failure-tracking list (e.g. `self.sync_failures`, `self.blueprint_sync_failures`), populate it in the two `handle_*_finished` callbacks, and branch the terminal `QMessageBox` between `.information` (all succeeded) and `.warning` (listing what failed) — mirroring `run_next_upgrade_queue`'s already-updated shape exactly.

**Tests:** Extend existing UI-flow tests (if any exist for these paths — check `tests/` for `main_window` coverage first) or add targeted ones asserting the warning path fires when a mock `ExecutionWorker` reports `success=False`.

---

## 8. Parallelize the Batch-Upgrade Queue Across Independent Managers

**Problem:** `run_next_upgrade_queue` processes `self.upgrade_queue` strictly one item at a time (`pop(0)`, wait for `finished_signal`, then pop the next) even when two queued items are for completely unrelated managers (e.g. npm and cargo) with no shared resource. `ScanWorker` already runs all managers concurrently via `asyncio.gather` — the upgrade path doesn't use the same approach.

**Files:** Modify `app/ui/main_window.py` (`start_batch_upgrade`, `run_next_upgrade_queue`)

**Design consideration to raise with the user before implementing:** parallel upgrades multiply concurrent `pkexec` prompts — if 3 managers all need elevation, the user could get 3 simultaneous polkit dialogs, which is a worse UX than the current one-at-a-time flow even though it's faster. Recommend: parallelize only the *non-elevated* items in the queue (check `cmd[0] != "pkexec"` before dispatch) and keep elevated items sequential, OR gate parallelism behind a settings toggle defaulting to off. Don't parallelize unconditionally without user sign-off on the multi-polkit-prompt tradeoff.

---

## 9. `list_installed()` and Similar Bare `except Exception: return []` Blocks Mask Network/Registry Failures

**Problem:** Same blind spot the fix-plan already called out for `check_updates()` (see the `"error"` dict misread as a package fix in `npm.py:74-77`) exists in `list_installed()` across nearly every driver (npm, cargo, pipx, gem, etc.) — a registry timeout or transient CLI error is indistinguishable from "genuinely zero packages installed."

**Files:** `app/core/drivers/*.py` (audit each `list_installed`)

**Resolution:** This is lower-priority polish, not a rewrite — apply the same targeted fix pattern already used for npm's `check_updates` (distinguish a real empty result from a caught exception) only where it's cheap: change `except Exception: return []` to `except Exception as e: raise RuntimeError(f"{self.name} list_installed failed: {e}") from e` in the highest-traffic drivers (npm, cargo, dnf, pacman) first, and let callers (`FetchInstalledWorker`) decide whether to show "0 installed" vs. "check failed" in the UI. Don't touch the lower-value drivers (Julia, Hex, cpanm) where `check_updates` is already an intentional `[]` stub per the language-dev-expansion plan — changing their error semantics isn't worth the churn.

---

## 10. Split `self.upgrade_queue`'s Overloaded Tuple Shape

**Problem:** `self.upgrade_queue` (declared once, `app/ui/main_window.py:677`, typed as `list[tuple[PackageManager, list[str]]]`) is reused across three unrelated flows with three different actual tuple shapes:
- Batch upgrade (`start_batch_upgrade`/`run_next_upgrade_queue`): `(manager, packages: list[str])`
- Repo sync (`sync_repositories`/`run_next_sync_queue`): `(manager, cmd: list[str])`
- Blueprint install (`export_local_configuration`'s sibling/`run_next_blueprint_sync`): `(manager, pkg: str, cmd: list[str])`

The type annotation only reflects the first shape. This works today because each flow fully drains the queue before another flow touches it, but it's exactly the kind of shared-mutable-state setup that produces a hard-to-trace bug the moment two flows are ever triggered close together, or a future edit assumes the annotated shape.

**Files:** Modify `app/ui/main_window.py`

**Resolution:** Introduce three dedicated attributes — `self.upgrade_queue`, `self.sync_queue`, `self.blueprint_install_queue` — each correctly typed for its actual tuple shape, and update the three flows' `.clear()`/`.append()`/`.pop(0)` call sites accordingly. Purely mechanical; no behavior change. Do this **before** Task 6 (retry action) and Task 8 (parallelization) — both add more state to the upgrade queue specifically, and doing so against the correctly-scoped `self.upgrade_queue` (rather than the currently-shared one) avoids compounding the ambiguity further.

---

## Wrap-up

**Files:** `tests/test_catalog.py` (extend for Task 4's new `apt` entry, following the existing has_driver-consistency check pattern), full suite run via `QT_QPA_PLATFORM=offscreen python3 -m pytest tests/ -q` before considering any task complete.
