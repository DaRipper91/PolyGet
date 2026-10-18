import os
import glob
import asyncio
import shutil
import shlex
import sys
import time
from pathlib import Path
from typing import Any
from PySide6.QtCore import Qt, QThread, Signal, Slot, QSize, QUrl, QSettings, QTimer
from PySide6.QtGui import QIcon, QDesktopServices, QPixmap, QColor, QKeySequence, QShortcut
from dataclasses import dataclass, field
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QTextEdit, QPlainTextEdit, QProgressBar, QMessageBox, QCheckBox,
    QLineEdit, QStackedWidget, QSplitter, QFrame, QComboBox, QFileDialog,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QMenu, QScrollArea, QSpinBox, QSystemTrayIcon,
    QApplication, QSizePolicy, QStyle, QToolButton, QDialog
)
from app.core.arch import describe_system
from app.core.manager import DriverError, PackageManager, describe_error, discover_managers
from app.core.coordinator import SubprocessCoordinator
from app.core.blueprint import BlueprintManager
from app.core.version_scan import cross_manager_newest
from app.core.sudo_secret import load as load_sudo_password
from app.core.debug_log import debug_log
from app.ui.updates_view import ManagerGroupHeader, SelectionBar
from app.ui.review_dialog import BuildScriptDialog, BuildScriptWorker, has_build_scripts
from app.ui import theme_qt, themes
from app.ui.icons import app_icon, tray_icon
from app.ui.sidebar import (
    DEFAULT_HEADER_STYLE, DEFAULT_NAV_STYLE, HEADER_STYLES, NAV_STYLES, BannerHeader,
    BrandHeader, GroupedNav, NavEntry, RailNav, StatusCard,
)


def find_icon_for_package(pkg_name: str, manager_name: str) -> str:
    """Scan standard desktop launcher files to resolve application icons."""
    if manager_name == "NPM":
        return "nodejs"
    if manager_name == "Cargo":
        return "rust"
    if manager_name == "Pipx":
        return "python"

    paths = [
        "/var/lib/flatpak/exports/share/applications",
        os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
        "/usr/share/applications",
        os.path.expanduser("~/.local/share/applications")
    ]

    for base_path in paths:
        if not os.path.exists(base_path):
            continue
        # Check {pkg_name}.desktop
        desktop_file = os.path.join(base_path, f"{pkg_name}.desktop")
        if os.path.exists(desktop_file):
            icon = _parse_icon_from_file(desktop_file)
            if icon:
                return icon
        # Try wildcard search
        matches = glob.glob(os.path.join(base_path, f"*{pkg_name}*.desktop"))
        for match in matches:
            icon = _parse_icon_from_file(match)
            if icon:
                return icon

    # System-level fallbacks
    if manager_name == "DNF":
        return "system-software-update"
    if manager_name == "Flatpak":
        return "package-x-generic"
    return "package-x-generic"


def _parse_icon_from_file(filepath: str) -> str | None:
    try:
        with open(filepath, "r", errors="ignore") as f:
            for line in f:
                if line.startswith("Icon="):
                    return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return None


class ScanWorker(QThread):
    """Worker thread to run all package manager scans concurrently using asyncio.gather."""
    log_signal = Signal(str)
    updates_signal = Signal(str, list)  # manager_name, list of updates
    error_signal = Signal(str, str)  # manager_name, error message
    unsupported_signal = Signal(str, str)  # manager_name, why it can't report outdated packages
    finished_all = Signal()

    def __init__(self, managers: list[PackageManager], parent: Any = None):
        super().__init__(parent)
        self.managers = managers

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def run_scan(mgr):
            self.log_signal.emit(f"🔍 Scanning {mgr.name} for updates...")
            debug_log.emit(f"[ScanWorker] scanning {mgr.name}")
            try:
                updates = await mgr.check_updates()
                self.updates_signal.emit(mgr.name, updates)
                self.log_signal.emit(f"✅ Scan complete for {mgr.name}. Found {len(updates)} update(s).")
                debug_log.emit(f"[ScanWorker] {mgr.name}: {len(updates)} update(s)")
            except NotImplementedError as e:
                self.log_signal.emit(f"ℹ️ {mgr.name} cannot report outdated packages ({describe_error(e)}); skipped.")
                self.unsupported_signal.emit(mgr.name, describe_error(e))
            except Exception as e:
                self.log_signal.emit(f"❌ Error scanning {mgr.name}: {str(e)}")
                self.error_signal.emit(mgr.name, str(e))
                debug_log.emit(f"[ScanWorker] {mgr.name}: error: {str(e)}")

        tasks = [run_scan(mgr) for mgr in self.managers]
        if tasks:
            loop.run_until_complete(asyncio.gather(*tasks))
        loop.close()
        self.finished_all.emit()


class VersionCheckWorker(QThread):
    """Worker thread to run the cross-manager newest-version scan."""
    log_signal = Signal(str)
    suggestions_signal = Signal(list, dict)  # suggestions, manager_status
    error_signal = Signal(str)  # error message

    def __init__(self, managers: list[PackageManager], parent: Any = None):
        super().__init__(parent)
        self.managers = managers

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            self.log_signal.emit("🔍 Running cross-manager version scan...")
            debug_log.emit("[VersionCheckWorker] running cross-manager scan")
            from app.core.settings_store import get_settings
            result = loop.run_until_complete(cross_manager_newest(self.managers, settings=get_settings()))
            suggestions = result.get("suggestions", [])
            manager_status = result.get("managers", {})
            self.suggestions_signal.emit(suggestions, manager_status)
            self.log_signal.emit(f"✅ Version scan complete. Found {len(suggestions)} suggestion(s).")
            debug_log.emit(f"[VersionCheckWorker] {len(suggestions)} suggestion(s)")
        except Exception as e:
            self.error_signal.emit(str(e))
            debug_log.emit(f"[VersionCheckWorker] error: {str(e)}")
        finally:
            loop.close()


class FetchReposWorker(QThread):
    """Asynchronous worker to fetch repository/remote listings without blocking the GUI."""
    result_signal = Signal(list)
    error_signal = Signal(str)

    def __init__(self, manager: PackageManager, parent: Any = None):
        super().__init__(parent)
        self.manager = manager

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            debug_log.emit(f"[FetchReposWorker] fetching repos for {self.manager.name}")
            repos = loop.run_until_complete(self.manager.list_repos())
            self.result_signal.emit(repos)
            debug_log.emit(f"[FetchReposWorker] {self.manager.name}: {len(repos)} repo(s)")
        except Exception as e:
            self.error_signal.emit(str(e))
            debug_log.emit(f"[FetchReposWorker] {self.manager.name}: error: {str(e)}")
        finally:
            loop.close()


class ExecutionWorker(QThread):
    """General purpose execution worker piping command outputs to the logs.

    If the command starts with ``pkexec`` and fails because no polkit
    authentication agent is bound to the session (common over SSH or in a
    minimal terminal), the worker transparently retries with ``sudo`` instead.
    A saved sudo password (keyring via :mod:`app.core.sudo_secret`) is supplied
    to ``sudo -S``; an empty password works for NOPASSWD sudoers entries.
    """

    log_signal = Signal(str)
    finished_signal = Signal(bool)

    _PKEXEC_NO_AGENT_MARKERS = (
        "authentication agent",
        "no session for cookie",
        "not authorized",
        "cannot determine the session",
    )

    def __init__(self, cmd: list[str], parent: Any = None):
        super().__init__(parent)
        self.cmd = cmd

    @staticmethod
    def _looks_like_pkexec_no_agent_failure(stderr_text: str) -> bool:
        """True when pkexec failed specifically because no polkit agent is bound.

        Checks each stderr line individually (rather than the whole blob) so a
        marker that merely appears inside a longer, unrelated error message
        does not trigger a false-positive sudo retry.
        """
        for line in stderr_text.splitlines():
            lowered = line.lower()
            if any(marker in lowered for marker in ExecutionWorker._PKEXEC_NO_AGENT_MARKERS):
                return True
        return False

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        cmd_str = " ".join(self.cmd)
        self.log_signal.emit(f"⚡ Executing: {cmd_str}")
        debug_log.emit(f"> {cmd_str}")
        try:
            async def run_once(cmd: list[str], password: str | None = None) -> tuple[int, list[str]]:
                """Run one command attempt; returns (returncode, stderr_lines)."""
                stdin_kind: int = (
                    asyncio.subprocess.PIPE if password is not None else asyncio.subprocess.DEVNULL
                )
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=stdin_kind,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=True,
                )
                coordinator = SubprocessCoordinator()
                coordinator.register(proc.pid)
                stderr_lines: list[str] = []
                try:
                    async def read_stream(
                        stream: asyncio.StreamReader, capture: list[str] | None = None,
                        stream_name: str = "stdout",
                    ) -> None:
                        while True:
                            line = await stream.readline()
                            if not line:
                                break
                            text = line.decode(errors="ignore").rstrip()
                            if capture is not None:
                                capture.append(text)
                            self.log_signal.emit(text)
                            debug_log.emit(f"[{stream_name}] {text}")

                    if password is not None:
                        assert proc.stdin is not None
                        proc.stdin.write(password.encode() + b"\n")
                        await proc.stdin.drain()
                    if proc.stdin is not None:
                        proc.stdin.close()

                    await asyncio.gather(
                        read_stream(proc.stdout),
                        read_stream(proc.stderr, stderr_lines, stream_name="stderr"),
                        proc.wait(),
                    )
                finally:
                    coordinator.unregister(proc.pid)
                return proc.returncode, stderr_lines

            async def run_with_fallback() -> int:
                cmd = list(self.cmd)
                is_pkexec = bool(cmd) and cmd[0] == "pkexec"

                code, stderr_lines = await run_once(cmd)
                if code == 0:
                    debug_log.emit(f"< exit {code} (ok)")
                    return 0

                stderr_text = "\n".join(stderr_lines)

                # pkexec failed because no polkit agent is bound: retry with sudo.
                if is_pkexec and self._looks_like_pkexec_no_agent_failure(stderr_text):
                    sudo_cmd = ["sudo"] + cmd[1:]
                    if "-S" not in sudo_cmd:
                        sudo_cmd.insert(1, "-S")
                    self.log_signal.emit(
                        " ⚠️ No polkit authentication agent bound to this session — "
                        "falling back to sudo."
                    )
                    debug_log.emit(f"! pkexec no-auth-agent → retrying with sudo: {' '.join(sudo_cmd)}")
                    password = load_sudo_password()
                    if password is None:
                        # No stored password and no NOPASSWD sudoers entry: the sudo
                        # retry cannot authenticate. Surface a clear failure instead
                        # of attempting a DEVNULL-stdin retry that is guaranteed to
                        # fail. (The TUI prompts the user here; the GUI cannot
                        # show a modal from a worker thread.)
                        self.log_signal.emit(
                            " ⚠️ No stored sudo password and sudo is not NOPASSWD — "
                            "cannot fall back to sudo. Store a password in the keyring "
                            "(TUI) or configure NOPASSWD sudo for this command."
                        )
                        debug_log.emit(f"< exit {code} (failed — no password for sudo)")
                        return code
                    code2, _ = await run_once(sudo_cmd, password=password)
                    debug_log.emit(f"< exit {code2} ({'ok' if code2 == 0 else 'failed'})")
                    return code2

                debug_log.emit(f"< exit {code} (failed)")
                return code

            exit_code = loop.run_until_complete(run_with_fallback())
            self.finished_signal.emit(exit_code == 0)
        except Exception as e:
            self.log_signal.emit(f"❌ Execution error: {str(e)}")
            debug_log.emit(f"! error: {str(e)}")
            self.finished_signal.emit(False)
        loop.close()


class SearchWorker(QThread):
    """Worker thread to run asynchronous searches across active package managers."""
    results_signal = Signal(list)
    log_signal = Signal(str)

    def __init__(self, query: str, source_filter: str = "All", parent: Any = None):
        super().__init__(parent)
        self.query = query
        self.source_filter = source_filter

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        results = []

        from app.core.manager import discover_managers
        managers = discover_managers()

        async def search_one(mgr):
            if self.source_filter not in ("All", "All Sources", mgr.name):
                return
            debug_log.emit(f"[SearchWorker] searching {mgr.name} for '{self.query}'")
            try:
                items = await mgr.search_packages(self.query)
                for item in items:
                    item.setdefault("source", mgr.name)
                    results.append(item)
            except NotImplementedError:
                # This manager has no search API. Expected, not worth a warning.
                pass
            except Exception as e:
                # A registry that failed is NOT the same as a registry that found
                # nothing, and must not be silently folded into an empty result.
                self.log_signal.emit(
                    f"⚠️ {mgr.name} search failed (results below exclude it): {str(e)}"
                )
                debug_log.emit(f"[SearchWorker] {mgr.name}: error: {str(e)}")

        tasks = [search_one(m) for m in managers]
        if tasks:
            loop.run_until_complete(asyncio.gather(*tasks))
        loop.close()

        # Tell the user when nothing came back at all *and* some manager failed, so a
        # dead registry is never presented as "no packages match your query".
        if not results and self.query:
            total = len(managers)
            self.log_signal.emit(
                f"⚠️ No results for '{self.query}' across {total} manager(s). "
                "If some managers failed above, their results are missing from this."
            )
        debug_log.emit(f"[SearchWorker] {len(results)} result(s) for '{self.query}'")
        self.results_signal.emit(results)


class CategoryWorker(QThread):
    """Worker thread to run asynchronous appstream category fetches."""
    results_signal = Signal(list)
    log_signal = Signal(str)

    def __init__(self, category: str, source_filter: str = "All", parent: Any = None):
        super().__init__(parent)
        self.category = category
        self.source_filter = source_filter

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        results = []

        if shutil.which("appstreamcli") is None:
            self.log_signal.emit(
                "⚠️ Category browsing requires the 'appstream' package "
                "(provides appstreamcli) — not found on this system."
            )
            self.results_signal.emit([])
            return

        # Map display name to appstream category name if needed
        # Standard AppStream categories:
        # Development, Game, Graphics, Network, Office, Science, System, Utility, AudioVideo
        cat_map = {
            "Development": "Development",
            "Games": "Game",
            "Graphics": "Graphics",
            "Internet": "Network",
            "Office": "Office",
            "Science": "Science",
            "System": "System",
            "Utilities": "Utility",
            "Video & Audio": "AudioVideo"
        }
        
        target = cat_map.get(self.category)
        if not target:
            self.results_signal.emit([])
            return

        self.log_signal.emit(f"📂 Fetching category: {self.category}...")
        debug_log.emit(f"[CategoryWorker] fetching category {self.category}")
        
        from app.core.distro import get_system_manager_name
        system_manager = get_system_manager_name()

        async def fetch_category():
            try:
                proc = await asyncio.create_subprocess_exec(
                    "appstreamcli", "list-categories", target,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, _ = await proc.communicate()
                
                components = []
                current = {}
                for line in stdout.decode(errors="ignore").splitlines():
                    line_str = line.strip()
                    if line_str == "---":
                        if current:
                            components.append(current)
                            current = {}
                        continue
                    if ":" in line_str:
                        key, val = line_str.split(":", 1)
                        current[key.strip().lower()] = val.strip()
                if current:
                    components.append(current)

                for comp in components:
                    name = comp.get("name")
                    summary = comp.get("summary", "")
                    icon = comp.get("icon", "")
                    
                    source = None
                    pkg_id = None
                    
                    if "bundle" in comp:
                        bundle = comp["bundle"]
                        if bundle.startswith("flatpak:"):
                            parts = bundle.split("/")
                            if len(parts) >= 2:
                                pkg_id = parts[1]
                                source = "Flatpak"
                    elif "package" in comp and system_manager:
                        # A distro package: owned by this distro's manager, not always DNF.
                        pkg_id = comp["package"]
                        source = system_manager

                    if source and pkg_id and name:
                        # Apply source filter
                        if self.source_filter == "All" or self.source_filter == source:
                            results.append({
                                "name": name,
                                "id": pkg_id,
                                "description": summary,
                                "version": "",
                                "source": source,
                                "remote": "flathub",
                                "icon": icon
                            })
            except Exception as e:
                self.log_signal.emit(f"Category fetch error: {str(e)}")

        loop.run_until_complete(fetch_category())
        loop.close()
        debug_log.emit(f"[CategoryWorker] {len(results)} result(s) for {self.category}")
        self.results_signal.emit(results)


class FetchInstalledWorker(QThread):
    """Worker thread to query installed packages across all available managers."""
    log_signal = Signal(str)
    result_signal = Signal(dict)  # manager -> package names (succeeded only)
    error_signal = Signal(dict)   # manager -> error message (failed)

    def __init__(self, managers: list[PackageManager], parent: Any = None):
        super().__init__(parent)
        self.managers = managers

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        self.log_signal.emit("🔍 Querying installed packages across all managers...")
        debug_log.emit("[FetchInstalledWorker] querying installed packages")
        results = {}
        errors = {}
        
        async def fetch_installed(mgr: PackageManager):
            self.log_signal.emit(f"📦 Querying installed packages from {mgr.name}...")
            try:
                pkgs = await mgr.list_installed()
                self.log_signal.emit(f"✅ Found {len(pkgs)} installed packages for {mgr.name}.")
                return mgr.name, pkgs, None
            except Exception as e:
                # Record the failure instead of folding it into an empty list: a dead
                # driver and a manager with nothing installed must not look alike.
                self.log_signal.emit(f"❌ Error querying {mgr.name}: {str(e)}")
                return mgr.name, None, str(e)

        tasks = [fetch_installed(mgr) for mgr in self.managers]
        done = loop.run_until_complete(asyncio.gather(*tasks))
        loop.close()
        
        for name, pkgs, err in done:
            if err is not None:
                errors[name] = err
            else:
                results[name] = pkgs or []
            
        debug_log.emit(f"[FetchInstalledWorker] {len(results)} manager(s) queried")
        self.result_signal.emit(results)
        self.error_signal.emit(errors)


class RemovePreviewWorker(QThread):
    """Ask a driver what removing a package would take with it, off the UI thread."""
    # (packages the removal takes out, or None when the manager has no dry run; error message,
    # "" on success). An error means the removal is blocked or couldn't be checked: don't run it.
    result_signal = Signal(object, str)

    def __init__(self, manager: PackageManager, package: str, parent: Any = None):
        super().__init__(parent)
        self.manager = manager
        self.package = package

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            preview = loop.run_until_complete(self.manager.preview_remove([self.package]))
            self.result_signal.emit(preview, "")
        except NotImplementedError:
            self.result_signal.emit(None, "")  # no dry run: the remove command is the whole plan
        except Exception as e:
            self.result_signal.emit(None, describe_error(e))
        finally:
            loop.close()


class FetchManagerVersionsWorker(QThread):
    """Worker thread to fetch each package manager's own version string."""
    result_signal = Signal(dict)  # manager_name -> version string

    def __init__(self, managers: list[PackageManager], parent: Any = None):
        super().__init__(parent)
        self.managers = managers

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        results = {}

        async def fetch_version(mgr: PackageManager):
            try:
                v = await mgr.get_self_version()
                return mgr.name, v
            except Exception:
                return mgr.name, None

        tasks = [fetch_version(m) for m in self.managers]
        if tasks:
            done = loop.run_until_complete(asyncio.gather(*tasks))
        loop.close()

        for name, version in done:
            results[name] = version
        self.result_signal.emit(results)


class UpdateItemWidget(QWidget):
    """Custom row widget replicating KDE Discover's update list items."""
    checked_changed = Signal(bool, str, str)
    menu_requested = Signal(object)  # the "⋯" button; same menu as right-click, for touch

    def __init__(self, pkg: dict[str, Any], manager_name: str, note: str = "", parent: Any = None):
        super().__init__(parent)
        self.pkg = pkg
        self.pkg_name = pkg.get("name", "")
        self.manager_name = manager_name
        self.setup_ui(pkg, manager_name, note)

    def setup_ui(self, pkg: dict[str, Any], manager_name: str, note: str = ""):
        self.setObjectName("update-item-card")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(15)

        self.checkbox = QCheckBox()
        self.checkbox.setChecked(True)
        self.checkbox.stateChanged.connect(self.on_checkbox_toggled)
        layout.addWidget(self.checkbox)

        self.lbl_icon = QLabel()
        self.lbl_icon.setFixedSize(40, 40)
        self.lbl_icon.setScaledContents(True)
        
        icon_name = find_icon_for_package(self.pkg_name, manager_name)
        qicon = QIcon.fromTheme(icon_name)
        if not qicon.isNull():
            self.lbl_icon.setPixmap(qicon.pixmap(40, 40))
        else:
            self.lbl_icon.setPixmap(QIcon.fromTheme("package-x-generic").pixmap(40, 40))
        layout.addWidget(self.lbl_icon)

        details_layout = QVBoxLayout()
        details_layout.setSpacing(2)
        
        lbl_name = QLabel(self.pkg_name)
        lbl_name.setStyleSheet("font-weight: bold; font-size: 14px; color: #ffffff;")
        details_layout.addWidget(lbl_name)

        cur_ver = pkg.get('current', '')
        new_ver = pkg.get('new', '')
        version_info = f"{cur_ver}  ➔  {new_ver}"
        lbl_version = QLabel(version_info)
        
        # Calculate Semver color (Major = Red/Pink #f38ba8, Minor = Yellow #f9e2af, Patch = Green #a6e3a1)
        semver_color = "#9ca3af"
        try:
            c_clean = cur_ver.lstrip("v").split("(")[0].strip()
            n_clean = new_ver.lstrip("v").split("(")[0].strip()
            c_parts = [int(p) for p in c_clean.split(".") if p.isdigit()]
            n_parts = [int(p) for p in n_clean.split(".") if p.isdigit()]
            if c_parts and n_parts:
                if n_parts[0] > c_parts[0]:
                    semver_color = "#f38ba8"  # Major bump
                elif len(n_parts) > 1 and len(c_parts) > 1 and n_parts[1] > c_parts[1]:
                    semver_color = "#f9e2af"  # Minor bump
                else:
                    semver_color = "#a6e3a1"  # Patch / build bump
        except Exception:
            pass

        lbl_version.setStyleSheet(f"color: {semver_color}; font-size: 12px;")
        details_layout.addWidget(lbl_version)

        if note:
            lbl_note = QLabel(note)
            lbl_note.setWordWrap(True)  # unwrapped, a long note sets the whole page's minimum width
            lbl_note.setStyleSheet("color: #fab387; font-size: 11px;")
            details_layout.addWidget(lbl_note)

        layout.addLayout(details_layout, 1)

        lbl_source = QLabel(manager_name)
        if manager_name == "DNF":
            badge_style = "background-color: #1e3a8a; color: #93c5fd;"
        elif manager_name == "Flatpak":
            badge_style = "background-color: #064e3b; color: #6ee7b7;"
        else:
            badge_style = "background-color: #581c87; color: #d8b4fe;"
        lbl_source.setStyleSheet(badge_style + "border-radius: 12px; padding: 4px 12px; font-weight: bold; font-size: 11px;")
        layout.addWidget(lbl_source, 0, Qt.AlignmentFlag.AlignVCenter)

        self.btn_menu = QPushButton("⋯")
        self.btn_menu.setFixedSize(44, 44)  # minimum comfortable touch target
        self.btn_menu.setToolTip("Package options")
        self.btn_menu.setAccessibleName(f"Options for {self.pkg_name}")
        self.btn_menu.setStyleSheet(
            "background-color: #313244; color: #cdd6f4; font-size: 20px; padding: 0; border-radius: 22px;"
        )
        self.btn_menu.clicked.connect(lambda: self.menu_requested.emit(self))
        layout.addWidget(self.btn_menu)

    def on_checkbox_toggled(self, state: int):
        self.checked_changed.emit(state == 2, self.pkg_name, self.manager_name)


class StoreItemWidget(QWidget):
    """Custom row widget representing search results in the package store."""
    install_requested = Signal(dict)
    remove_requested = Signal(str, str)  # manager name, package

    def __init__(self, item: dict[str, Any], parent: Any = None):
        super().__init__(parent)
        self.item = item
        self.setup_ui()

    def setup_ui(self):
        self.setObjectName("store-item-card")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(15)

        # Icon
        self.lbl_icon = QLabel()
        self.lbl_icon.setFixedSize(40, 40)
        self.lbl_icon.setScaledContents(True)
        
        icon_name = self.item.get("icon", "")
        if icon_name:
            if icon_name.endswith((".png", ".svg", ".xpm")):
                icon_name = icon_name.rsplit(".", 1)[0]
        else:
            icon_name = find_icon_for_package(self.item["id"], self.item["source"])
            
        qicon = QIcon.fromTheme(icon_name)
        if not qicon.isNull():
            self.lbl_icon.setPixmap(qicon.pixmap(40, 40))
        else:
            fallback = "package-x-generic" if self.item["source"] == "DNF" else "preferences-desktop-apps"
            self.lbl_icon.setPixmap(QIcon.fromTheme(fallback).pixmap(40, 40))
        layout.addWidget(self.lbl_icon)

        # Details Layout (Name & Subtitle description)
        details_layout = QVBoxLayout()
        details_layout.setSpacing(2)

        lbl_name = QLabel(self.item["name"])
        lbl_name.setStyleSheet("font-weight: bold; font-size: 14px; color: #ffffff;")
        details_layout.addWidget(lbl_name)

        lbl_desc = QLabel(self.item["description"])
        lbl_desc.setStyleSheet("color: #9ca3af; font-size: 12px;")
        lbl_desc.setWordWrap(True)
        details_layout.addWidget(lbl_desc)

        layout.addLayout(details_layout, stretch=1)

        # Source Badge
        lbl_source = QLabel(self.item["source"])
        if self.item["source"] == "DNF":
            badge_style = "background-color: #1e3a8a; color: #93c5fd;"
        else:
            badge_style = "background-color: #064e3b; color: #6ee7b7;"
        lbl_source.setStyleSheet(badge_style + "border-radius: 12px; padding: 4px 12px; font-weight: bold; font-size: 11px;")
        layout.addWidget(lbl_source)

        # Install Button (Remove… for rows from the Store's Installed view)
        installed = bool(self.item.get("installed"))
        self.btn_install = QPushButton("Remove…" if installed else "Install")
        self.btn_install.setAccessibleName(
            f"{'Remove' if installed else 'Install'} {self.item['name']}")
        self.btn_install.setStyleSheet("""
            QPushButton {
                background-color: #313244;
                color: #cdd6f4;
                padding: 6px 14px;
                font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #89b4fa;
                color: #11111b;
            }
        """)
        if installed:
            self.btn_install.clicked.connect(
                lambda: self.remove_requested.emit(self.item["source"], self.item["id"]))
        else:
            self.btn_install.clicked.connect(lambda: self.install_requested.emit(self.item))
        layout.addWidget(self.btn_install)


from app.core.catalog import CatalogEntry

class ManagerItemWidget(QWidget):
    """Custom row widget representing supported package managers."""
    install_requested = Signal(object)

    def __init__(self, entry: CatalogEntry, version: str | None = None, parent: Any = None):
        super().__init__(parent)
        self.entry = entry
        self.mgr_name = entry.name
        self.category = entry.category
        self.is_installed = entry.installed
        self.version = version
        self.setup_ui()

    def setup_ui(self):
        self.setObjectName("store-item-card")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(15)

        # Icon mapping
        self.lbl_icon = QLabel()
        self.lbl_icon.setFixedSize(40, 40)
        self.lbl_icon.setScaledContents(True)
        
        icon_map = {
            "DNF": "system-run",
            "Flatpak": "preferences-desktop-apps",
            "NPM": "nodejs",
            "Cargo": "rust",
            "Pipx": "python",
            "Pacman": "system-run",
            "APT": "system-run",
            "Zypper": "system-run",
            "APK": "system-run",
            "XBPS": "system-run",
            "Snap": "emblem-downloads",
            "Distrobox": "utilities-terminal"
        }
        icon_name = icon_map.get(self.mgr_name, self.entry.icon or "package-x-generic")
        qicon = QIcon.fromTheme(icon_name)
        if not qicon.isNull():
            self.lbl_icon.setPixmap(qicon.pixmap(40, 40))
        else:
            self.lbl_icon.setPixmap(QIcon.fromTheme("package-x-generic").pixmap(40, 40))
        layout.addWidget(self.lbl_icon)

        # Details
        details_layout = QVBoxLayout()
        details_layout.setSpacing(2)

        lbl_name = QLabel(f"{self.mgr_name} ({self.category})")
        if self.version:
            lbl_name.setText(f"{self.mgr_name} ({self.category}) — v{self.version}")
        lbl_name.setStyleSheet("font-weight: bold; font-size: 14px; color: #ffffff;")
        details_layout.addWidget(lbl_name)
        self._name_label = lbl_name

    def set_version(self, version: str | None) -> None:
        """Update the displayed version after it's been fetched asynchronously."""
        self.version = version
        if hasattr(self, "_name_label"):
            if version:
                self._name_label.setText(f"{self.mgr_name} ({self.category}) — v{version}")
            else:
                self._name_label.setText(f"{self.mgr_name} ({self.category})")

        lbl_desc = QLabel(self.entry.description)
        lbl_desc.setStyleSheet("color: #a6adc8; font-size: 12px;")
        lbl_desc.setWordWrap(True)
        details_layout.addWidget(lbl_desc)

        layout.addLayout(details_layout, stretch=1)

        # Status Badge
        lbl_status = QLabel("Active" if self.is_installed else "Not Installed")
        if self.is_installed:
            badge_style = "background-color: #064e3b; color: #6ee7b7; border-radius: 12px; padding: 4px 12px; font-weight: bold; font-size: 11px;"
        else:
            badge_style = "background-color: #7f1d1d; color: #fca5a5; border-radius: 12px; padding: 4px 12px; font-weight: bold; font-size: 11px;"
        lbl_status.setStyleSheet(badge_style)
        layout.addWidget(lbl_status)

        # Action Button
        if not self.is_installed:
            if not self.entry.has_driver:
                lbl_note = QLabel("Browsing only — driver coming later")
                lbl_note.setStyleSheet("color: #a6adc8; font-style: italic; font-size: 11px;")
                layout.addWidget(lbl_note)
            else:
                self.btn_action = QPushButton("Install")
                self.btn_action.setStyleSheet("""
                    QPushButton {
                        background-color: #313244;
                        color: #cdd6f4;
                        padding: 6px 14px;
                        font-weight: bold;
                        border-radius: 6px;
                    }
                    QPushButton:hover {
                        background-color: #89b4fa;
                        color: #11111b;
                    }
                    QPushButton:disabled {
                        background-color: #181825;
                        color: #585b70;
                    }
                """)
                
                # Check if install command is available for this distro family
                install_cmd = self.entry.get_self_install_command()
                if install_cmd is None:
                    self.btn_action.setEnabled(False)
                    self.btn_action.setToolTip("Not available for your distro family yet")
                    
                self.btn_action.clicked.connect(lambda: self.install_requested.emit(self.entry))
                layout.addWidget(self.btn_action)


class RepoItemWidget(QWidget):
    """Custom row widget representing a repository/remote source."""
    remove_requested = Signal(str)
    toggle_requested = Signal(str, bool)

    def __init__(self, repo: dict[str, Any], parent: Any = None):
        super().__init__(parent)
        self.repo_id = repo["id"]
        self.repo_name = repo["name"]
        self.repo_url = repo.get("url", "")
        self.is_enabled = repo.get("enabled", True)
        self.setup_ui()

    def setup_ui(self):
        self.setObjectName("update-item-card")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(15)

        # Checkbox/Toggle for Enable/Disable state
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(self.is_enabled)
        self.checkbox.stateChanged.connect(self.on_checkbox_toggled)
        layout.addWidget(self.checkbox)

        # Details
        details_layout = QVBoxLayout()
        details_layout.setSpacing(2)

        lbl_name = QLabel(self.repo_name)
        lbl_name.setStyleSheet("font-weight: bold; font-size: 13px; color: #ffffff;")
        details_layout.addWidget(lbl_name)

        if self.repo_url:
            lbl_url = QLabel(self.repo_url)
            lbl_url.setStyleSheet("color: #a6adc8; font-size: 11px;")
            lbl_url.setWordWrap(True)
            details_layout.addWidget(lbl_url)
            
        layout.addLayout(details_layout, stretch=1)

        # Status badge
        lbl_status = QLabel("Enabled" if self.is_enabled else "Disabled")
        if self.is_enabled:
            badge_style = "background-color: #064e3b; color: #6ee7b7; border-radius: 12px; padding: 4px 10px; font-weight: bold; font-size: 10px;"
        else:
            badge_style = "background-color: #313244; color: #a6adc8; border-radius: 12px; padding: 4px 10px; font-weight: bold; font-size: 10px;"
        lbl_status.setStyleSheet(badge_style)
        layout.addWidget(lbl_status)

        # Delete/Remove button
        self.btn_delete = QPushButton("Remove")
        self.btn_delete.setStyleSheet("""
            QPushButton {
                background-color: #7f1d1d;
                color: #fca5a5;
                padding: 6px 12px;
                font-weight: bold;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #fca5a5;
                color: #11111b;
            }
        """)
        self.btn_delete.clicked.connect(lambda: self.remove_requested.emit(self.repo_id))
        layout.addWidget(self.btn_delete)

    def on_checkbox_toggled(self, state: int):
        self.toggle_requested.emit(self.repo_id, state == 2)


_AUTOSTART_PATH = Path.home() / ".config" / "autostart" / "polyget.desktop"


def set_autostart(enabled: bool) -> None:
    """Add or remove a login autostart entry that launches PolyGet hidden in the tray."""
    if not enabled:
        _AUTOSTART_PATH.unlink(missing_ok=True)
        return
    run_py = Path(__file__).resolve().parents[2] / "run.py"
    _AUTOSTART_PATH.parent.mkdir(parents=True, exist_ok=True)
    _AUTOSTART_PATH.write_text(
        "[Desktop Entry]\nType=Application\nName=PolyGet\nIcon=polyget\n"
        f"Exec={shlex.quote(sys.executable)} {shlex.quote(str(run_py))} --tray\n"
        "X-GNOME-Autostart-enabled=true\n",
        encoding="utf-8",
    )


# Appended to the theme in touch mode: every tap target at least ~44px.
_TOUCH_QSS = """
QPushButton { min-height: 44px; }
QListWidget#nav-list::item { padding: 14px; }
QPushButton#nav-button { min-height: 44px; padding: 4px 12px; }
QToolButton#rail-button { min-height: 52px; }
QCheckBox { spacing: 14px; min-height: 44px; }
QCheckBox::indicator { width: 30px; height: 30px; border-radius: 6px; }
QLineEdit, QComboBox, QSpinBox { min-height: 44px; }
QListWidget#status-list::item { padding: 14px 10px; }
QTreeWidget::item { padding: 10px; }
QScrollBar:vertical { width: 16px; border-radius: 8px; }
QScrollBar::handle:vertical { min-height: 48px; border-radius: 8px; }
QScrollBar:horizontal { height: 16px; }
"""


# Sidebar rows and stacked pages share these indices; keep them in setup_ui's order.
(PAGE_UPDATES, PAGE_VERSION_CHECK, PAGE_STORE, PAGE_CONSOLE, PAGE_BLUEPRINTS,
 PAGE_MANAGERS, PAGE_REPOS, PAGE_HISTORY, PAGE_SETTINGS, PAGE_DEBUG) = range(10)

# (page, label, short rail label, icon-theme name) for the grouped and rail sidebar styles.
_NAV_PAGES = [
    (PAGE_UPDATES, "Updates", "Updates", "system-software-update"),
    (PAGE_VERSION_CHECK, "Version Check", "Versions", "view-refresh"),
    (PAGE_STORE, "Browse Store", "Store", "emblem-downloads"),
    (PAGE_CONSOLE, "Process Console", "Console", "utilities-terminal"),
    (PAGE_BLUEPRINTS, "Blueprints", "Blueprints", "document-properties"),
    (PAGE_MANAGERS, "Package Managers", "Managers", "preferences-system"),
    (PAGE_REPOS, "Repositories", "Repos", "applications-internet"),
    (PAGE_HISTORY, "Update History", "History", "document-open-recent"),
    (PAGE_SETTINGS, "Settings", "Settings", "configure"),
    (PAGE_DEBUG, "Debug Console", "Debug", "dialog-information"),
]
_NAV_GROUPS = [
    ("Software", [PAGE_UPDATES, PAGE_STORE, PAGE_VERSION_CHECK]),
    ("System", [PAGE_MANAGERS, PAGE_REPOS, PAGE_BLUEPRINTS]),
    ("Activity", [PAGE_CONSOLE, PAGE_HISTORY, PAGE_DEBUG]),
]


@dataclass
class UpgradeTask:
    """A single package-manager upgrade to run."""
    manager: PackageManager
    packages: list[str]


@dataclass
class SyncTask:
    """A repository-metadata sync to run."""
    manager: PackageManager
    command: list[str]


@dataclass
class BlueprintInstallTask:
    """A single package to install during a blueprint sync."""
    manager: PackageManager
    package: str
    command: list[str]


class MainWindow(QMainWindow):
    """Main window supporting unified updates, package browsing, and logs."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PolyGet")
        self.resize(1050, 700)
        self.managers: dict[str, PackageManager] = {}
        self.updates_cache: dict[str, list[dict[str, Any]]] = {}
        self.scan_errors: dict[str, str] = {}
        # Per-manager scan state for the Updates page's group headers: "scanning" | "done" |
        # "failed", plus when each last finished, so a single manager can be retried alone.
        self.manager_scan_state: dict[str, str] = {}
        self.manager_checked_at: dict[str, float] = {}
        self.unsupported_reasons: dict[str, str] = {}
        self.selected_updates: dict[str, set[str]] = {}
        self.active_workers: list[QThread] = []
        self.upgrade_queue: list[UpgradeTask] = []
        self._elevated_queue: list[UpgradeTask] = []
        self._parallel_queue: list[UpgradeTask] = []
        self._running_workers: int = 0
        self.sync_queue: list[SyncTask] = []
        self.blueprint_queue: list[BlueprintInstallTask] = []
        self.upgrade_failures: list[str] = []
        self.upgrade_results: dict[str, tuple[list[str], bool]] = {}
        self.upgrade_unbuildable: set[str] = set()  # failed because no command could be built: Retry would fail identically
        self.pending_verification: dict[str, tuple[list[str], bool]] | None = None
        self.sync_failures: list[str] = []
        self.blueprint_failures: list[tuple[str, str]] = []
        self.scan_in_progress = False
        self.scan_generation = 0
        self.store_generation = 0
        self.repos_generation = 0
        self.repos_selected_manager: str | None = None
        self.active_operation: str | None = None
        self.installing_managers: set[str] = set()
        self.installing_packages: set[str] = set()
        self.removing_packages: set[str] = set()
        self._reviewing_scripts = False  # an AUR build-script fetch for an upgrade is in flight
        self.repo_actions_in_flight: set[str] = set()

        self.tray: QSystemTrayIcon | None = None
        self.bg_timer = QTimer(self)
        self.bg_timer.timeout.connect(self.background_scan)
        self.notify_after_scan = False
        self.notified_updates: set[tuple[str, str, str]] = set()
        self.really_quit = False

        # Theme before any widget exists, so each is styled in the right colours from the start.
        self.theme_filter = theme_qt.install()
        self._select_theme()
        self.setup_ui()
        self.apply_window_icon()
        self.apply_touch_mode()
        self.apply_sidebar_style()
        hints = QApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(self._on_system_scheme_changed)
        self.restore_window_state()
        # Keeps the status card's "Checked N min ago" current between scans.
        self.sidebar_clock = QTimer(self)
        self.sidebar_clock.timeout.connect(self.refresh_sidebar_status)
        self.sidebar_clock.start(60_000)
        self.setup_tray()
        self._setup_keyboard_shortcuts()

        from app.core.settings_store import get_settings
        if get_settings().get("ui.scan_on_launch", True):
            self.scan_all()
        else:
            self.lbl_summary.setText("Press “Check for Updates” to scan.")

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter = splitter
        main_layout.addWidget(splitter)

        # --- Terminal Overlay (hidden by default, shows live logs during operations) ---
        self._build_terminal_overlay(main_layout)

        # --- Sidebar Panel ---
        # Every sidebar widget is built once here; apply_sidebar_style() picks which ones are
        # shown, and in what order, for the header and navigation styles chosen in Settings.
        sidebar_widget = QWidget()
        sidebar_widget.setObjectName("sidebar-panel")
        self.sidebar_widget = sidebar_widget
        sidebar_layout = QVBoxLayout(sidebar_widget)
        self.sidebar_layout = sidebar_layout
        sidebar_layout.setContentsMargins(12, 12, 12, 12)
        sidebar_layout.setSpacing(12)

        self.header_banner = BannerHeader()
        self.header_brand = BrandHeader()
        self.header_status = StatusCard()
        self.rail_mark = QLabel()
        self.rail_mark.setObjectName("rail-mark")
        self.rail_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rail_mark.setPixmap(self.header_brand.icon.pixmap().scaled(
            40, 40, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.rail_mark.setToolTip("PolyGet")
        self.last_scan_at: float | None = None
        self.sidebar_header_style = DEFAULT_HEADER_STYLE
        self.sidebar_nav_style = DEFAULT_NAV_STYLE
        sidebar_layout.addWidget(self.header_banner)
        sidebar_layout.setContentsMargins(12, 12, 12, 12)
        sidebar_layout.setSpacing(12)

        # Local Update Filters
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Filter local updates...")
        self.search_bar.setObjectName("search-bar")
        self.search_bar.textChanged.connect(self.filter_updates)
        sidebar_layout.addWidget(self.search_bar)

        # Nav List
        self.nav_list = QListWidget()
        self.nav_list.setObjectName("nav-list")
        
        item_store = QListWidgetItem("Browse Store")
        item_store.setIcon(QIcon.fromTheme("emblem-downloads"))
        self.nav_list.addItem(item_store)

        item_console = QListWidgetItem("Process Console")
        item_console.setIcon(QIcon.fromTheme("utilities-terminal"))
        self.nav_list.addItem(item_console)
        
        item_blueprints = QListWidgetItem("Blueprints")
        item_blueprints.setIcon(QIcon.fromTheme("document-properties"))
        self.nav_list.addItem(item_blueprints)
        
        item_managers = QListWidgetItem("Package Managers")
        item_managers.setIcon(QIcon.fromTheme("preferences-system"))
        self.nav_list.addItem(item_managers)
        
        item_repos = QListWidgetItem("Repositories")
        item_repos.setIcon(QIcon.fromTheme("applications-internet"))
        self.nav_list.addItem(item_repos)

        item_history = QListWidgetItem("Update History")
        item_history.setIcon(QIcon.fromTheme("document-open-recent"))
        self.nav_list.addItem(item_history)

        item_settings = QListWidgetItem("Settings")
        item_settings.setIcon(QIcon.fromTheme("configure"))
        self.nav_list.addItem(item_settings)

        item_debug = QListWidgetItem("Debug Console")
        item_debug.setIcon(QIcon.fromTheme("document-properties"))
        self.nav_list.addItem(item_debug)

        # A plain-text item's sizeHint (queried only once it's actually in the list — before
        # that, QListWidgetItem.sizeHint() isn't backed by a real style/delegate context) already
        # includes the ::item padding/margin QSS box. Reuse it verbatim for the widget-based row
        # below so both end up the exact same height instead of guessing at the QSS math.
        native_row_size = item_store.sizeHint()
        self.nav_native_row_size = native_row_size

        item_updates = QListWidgetItem()
        self.nav_list.insertItem(0, item_updates)
        updates_row, self.nav_updates_label, self.nav_updates_badge = self._create_nav_row(
            "system-software-update", "System Updates"
        )
        self.nav_list.setItemWidget(item_updates, updates_row)
        item_updates.setSizeHint(native_row_size)

        # VERSION CHECK row (index 1)
        item_version_check = QListWidgetItem()
        self.nav_list.insertItem(1, item_version_check)
        version_check_row, self.nav_version_check_label, self.nav_version_check_badge = self._create_nav_row(
            "view-refresh", "Version Check"
        )
        self.nav_list.setItemWidget(item_version_check, version_check_row)
        item_version_check.setSizeHint(native_row_size)

        # setCurrentRow(0) below fires before currentRowChanged is connected, so change_page(0)
        # never runs on startup — style this row as selected up front to match.
        self._style_nav_row_text(self.nav_updates_label, selected=True)

        self.nav_list.setCurrentRow(0)
        self.nav_list.currentRowChanged.connect(self.change_page)
        sidebar_layout.addWidget(self.nav_list)

        # Grouped and rail views mirror nav_list rather than replacing it, so every
        # nav_list.setCurrentRow(PAGE_X) call elsewhere keeps driving whichever view is shown.
        nav = {page: NavEntry(page, label, short, icon) for page, label, short, icon in _NAV_PAGES}
        groups = [(title, [nav[p] for p in pages]) for title, pages in _NAV_GROUPS]
        self.nav_grouped = GroupedNav(groups, [nav[PAGE_SETTINGS]])
        self.nav_rail = RailNav([nav[p] for _, pages in _NAV_GROUPS for p in pages], [nav[PAGE_SETTINGS]])
        for view in (self.nav_grouped, self.nav_rail):
            view.page_selected.connect(self.nav_list.setCurrentRow)
            view.set_current(PAGE_UPDATES)
            view.hide()
        self.nav_list.currentRowChanged.connect(self._sync_nav_views)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #374151;")
        self.sources_line = line
        sidebar_layout.addWidget(line)

        lbl_sources = QLabel("Active Repositories")
        lbl_sources.setObjectName("sidebar-title")
        self.lbl_sources = lbl_sources
        sidebar_layout.addWidget(lbl_sources)

        self.status_list = QListWidget()
        self.status_list.setObjectName("status-list")
        self.status_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.status_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.status_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        sidebar_layout.addWidget(self.status_list)

        self.btn_scan = QPushButton("Check for Updates")
        self.btn_scan.setObjectName("btn-scan")
        self.btn_scan.clicked.connect(self.scan_all)
        sidebar_layout.addWidget(self.btn_scan)

        self.btn_refresh_repos = QPushButton("Sync Repositories")
        self.btn_refresh_repos.setObjectName("btn-scan")
        self.btn_refresh_repos.clicked.connect(self.sync_repositories)
        sidebar_layout.addWidget(self.btn_refresh_repos)

        splitter.addWidget(sidebar_widget)

        # --- Stacked Pages Panel ---
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.setObjectName("central-stack")

        # PAGE 1: Updates List
        updates_page = QWidget()
        updates_layout = QVBoxLayout(updates_page)
        updates_layout.setContentsMargins(20, 20, 20, 20)
        updates_layout.setSpacing(15)

        updates_header = QHBoxLayout()
        self.updates_header = updates_header  # the rail style moves the filter box in here
        self.lbl_summary = QLabel("Checking for updates...")
        self.lbl_summary.setObjectName("summary-label")
        self.lbl_summary.setWordWrap(True)
        updates_header.addWidget(self.lbl_summary, 1)

        # One checkbox for all/some/none (replaces Select All + Deselect All) and one primary
        # Update button whose arrow holds the other ways to run an upgrade.
        self.chk_select_all = QCheckBox("")
        self.chk_select_all.setObjectName("select-all")
        self.chk_select_all.setTristate(True)
        self.chk_select_all.setAccessibleName("Select all updates")
        self.chk_select_all.clicked.connect(lambda _=False: self.toggle_all_selection())
        updates_header.addWidget(self.chk_select_all)

        self.btn_update_selected = QToolButton()
        self.btn_update_selected.setObjectName("btn-update-primary")
        self.btn_update_selected.setText("Update")
        self.btn_update_selected.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.btn_update_selected.setEnabled(False)
        self.btn_update_selected.clicked.connect(self.run_primary_update)
        update_menu = QMenu(self.btn_update_selected)
        self.act_update_selected = update_menu.addAction("Update selected")
        self.act_update_selected.triggered.connect(lambda: self.start_batch_upgrade())
        self.act_update_all = update_menu.addAction("Update all")
        self.act_update_all.triggered.connect(self.update_all)
        self.act_update_user = update_menu.addAction("Only user-level (no password)")
        self.act_update_user.triggered.connect(self.update_user_level)
        self.btn_update_selected.setMenu(update_menu)
        updates_header.addWidget(self.btn_update_selected)
        updates_layout.addLayout(updates_header)

        self.updates_list = QListWidget()
        self.updates_list.setObjectName("updates-list")
        self.updates_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.updates_list.customContextMenuRequested.connect(self.show_update_context_menu)
        updates_layout.addWidget(self.updates_list)

        self.selection_bar = SelectionBar()
        self.selection_bar.clear_requested.connect(self.deselect_all_updates)
        self.selection_bar.update_requested.connect(lambda: self.start_batch_upgrade())
        self.selection_bar.hide()
        updates_layout.addWidget(self.selection_bar)

        # Progress bar
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        updates_layout.addWidget(self.progress)

        self.stacked_widget.addWidget(updates_page)

        # PAGE 2: Version Check
        version_check_page = QWidget()
        version_check_layout = QVBoxLayout(version_check_page)
        version_check_layout.setContentsMargins(20, 20, 20, 20)
        version_check_layout.setSpacing(15)

        version_check_header = QHBoxLayout()
        self.lbl_version_check_summary = QLabel("Run a cross-manager version scan to find packages with newer versions on other managers.")
        self.lbl_version_check_summary.setObjectName("summary-label")
        self.lbl_version_check_summary.setWordWrap(True)  # else its length is the page's min width
        version_check_header.addWidget(self.lbl_version_check_summary, 1)

        self.btn_version_check = QPushButton("Run Version Scan")
        self.btn_version_check.setObjectName("btn-scan")
        self.btn_version_check.clicked.connect(self.run_version_check)
        version_check_header.addWidget(self.btn_version_check)

        self.btn_version_check_refresh = QPushButton("Refresh")
        self.btn_version_check_refresh.setObjectName("btn-scan")
        self.btn_version_check_refresh.clicked.connect(self.run_version_check)
        version_check_header.addWidget(self.btn_version_check_refresh)
        version_check_layout.addLayout(version_check_header)

        # Toolbar for version check actions
        vc_toolbar = QHBoxLayout()
        self.chk_show_ignored = QCheckBox("Show ignored")
        self.chk_show_ignored.setToolTip("Include suggestions where all versions are in ignore list")
        self.chk_show_ignored.stateChanged.connect(self.run_version_check)
        vc_toolbar.addWidget(self.chk_show_ignored)

        self.chk_show_alias = QCheckBox("Show alias-matched")
        self.chk_show_alias.setToolTip("Include suggestions matched via alias map")
        self.chk_show_alias.setChecked(True)
        self.chk_show_alias.stateChanged.connect(self.run_version_check)
        vc_toolbar.addWidget(self.chk_show_alias)
        vc_toolbar.addStretch()
        version_check_layout.addLayout(vc_toolbar)

        # Tree widget for expandable suggestions
        self.version_check_tree = QTreeWidget()
        self.version_check_tree.setObjectName("version-check-tree")
        self.version_check_tree.setHeaderLabels(["Package", "Newest Manager", "Newest Version", "Installed Versions", "Note"])
        self.version_check_tree.setAlternatingRowColors(True)
        self.version_check_tree.setRootIsDecorated(True)
        self.version_check_tree.setExpandsOnDoubleClick(True)
        self.version_check_tree.header().setStretchLastSection(False)
        self.version_check_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.version_check_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.version_check_tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.version_check_tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.version_check_tree.header().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.version_check_tree.itemDoubleClicked.connect(self.show_version_check_detail)
        version_check_layout.addWidget(self.version_check_tree)

        self.version_check_progress = QProgressBar()
        self.version_check_progress.setVisible(False)
        version_check_layout.addWidget(self.version_check_progress)

        self.stacked_widget.addWidget(version_check_page)

        # PAGE 3: Browse Store
        store_page = QWidget()
        store_layout = QHBoxLayout(store_page)
        store_layout.setContentsMargins(0, 0, 0, 0)
        store_layout.setSpacing(0)

        store_splitter = QSplitter(Qt.Orientation.Horizontal)
        store_layout.addWidget(store_splitter)

        # Left side of Store Page: Categories Panel
        store_sidebar = QWidget()
        store_sidebar.setObjectName("store-sidebar")
        store_sidebar.setStyleSheet("""
            QWidget#store-sidebar {
                background-color: #11111b;
                border-right: 1px solid #313244;
            }
        """)
        store_sidebar_layout = QVBoxLayout(store_sidebar)
        store_sidebar_layout.setContentsMargins(12, 12, 12, 12)
        store_sidebar_layout.setSpacing(10)

        lbl_cat_title = QLabel("Categories")
        lbl_cat_title.setObjectName("sidebar-title")
        store_sidebar_layout.addWidget(lbl_cat_title)

        self.store_category_list = QListWidget()
        self.store_category_list.setObjectName("nav-list")
        self.store_category_list.addItems([
            "All Categories",
            "Development",
            "Games",
            "Graphics",
            "Internet",
            "Office",
            "Science",
            "System",
            "Utilities",
            "Video & Audio"
        ])
        self.store_category_list.setCurrentRow(0)
        self.store_category_list.currentRowChanged.connect(self.on_category_changed)
        store_sidebar_layout.addWidget(self.store_category_list)
        store_splitter.addWidget(store_sidebar)

        # Right side of Store Page: App Grid / List
        store_content = QWidget()
        store_content_layout = QVBoxLayout(store_content)
        store_content_layout.setContentsMargins(20, 20, 20, 20)
        store_content_layout.setSpacing(15)

        # Store Search Header
        store_header = QHBoxLayout()
        self.txt_store_search = QLineEdit()
        self.txt_store_search.setPlaceholderText("Search online apps and software packages...")
        self.txt_store_search.setObjectName("search-bar")
        self.txt_store_search.returnPressed.connect(self.perform_store_search)
        store_header.addWidget(self.txt_store_search, stretch=3)

        self.combo_source = QComboBox()
        from app.core.manager import discover_managers
        mgr_names = [m.name for m in discover_managers()]
        self.combo_source.addItems(["All Sources"] + sorted(mgr_names))
        store_header.addWidget(self.combo_source, stretch=1)
        self.combo_source.currentTextChanged.connect(self.filter_store_results)

        self.chk_store_installed = QCheckBox("Installed")
        self.chk_store_installed.setToolTip("Show packages already installed, with a Remove button")
        self.chk_store_installed.toggled.connect(self.on_store_installed_toggled)
        store_header.addWidget(self.chk_store_installed)

        btn_search = QPushButton("Search")
        btn_search.clicked.connect(self.perform_store_search)
        store_header.addWidget(btn_search)
        store_content_layout.addLayout(store_header)

        self.lbl_store_results = QLabel("Type a query and press enter to search or select a category to browse...")
        self.lbl_store_results.setObjectName("summary-label")
        store_content_layout.addWidget(self.lbl_store_results)

        self.store_list = QListWidget()
        self.store_list.setObjectName("updates-list")
        store_content_layout.addWidget(self.store_list)

        store_splitter.addWidget(store_content)
        store_splitter.setSizes([200, 800])

        self.stacked_widget.addWidget(store_page)

        # PAGE 3: Console Logs
        console_page = QWidget()
        console_layout = QVBoxLayout(console_page)
        console_layout.setContentsMargins(20, 20, 20, 20)
        console_layout.setSpacing(15)

        console_header = QHBoxLayout()
        lbl_console_title = QLabel("Execution Console Stream")
        lbl_console_title.setObjectName("summary-label")
        console_header.addWidget(lbl_console_title)
        console_header.addStretch()

        btn_clear = QPushButton("Clear Output")
        btn_clear.clicked.connect(self.console_clear)
        console_header.addWidget(btn_clear)
        console_layout.addLayout(console_header)

        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setObjectName("console-output")
        console_layout.addWidget(self.console)

        self.stacked_widget.addWidget(console_page)

        # PAGE 4: Blueprints
        blueprints_page = QWidget()
        blueprints_layout = QVBoxLayout(blueprints_page)
        blueprints_layout.setContentsMargins(20, 20, 20, 20)
        blueprints_layout.setSpacing(15)

        lbl_desc = QLabel("Declarative Environment Sync\nDefine your system's package state in a YAML blueprint to import, export, or sync package manager drift.")
        lbl_desc.setObjectName("summary-label")
        lbl_desc.setWordWrap(True)
        blueprints_layout.addWidget(lbl_desc)

        blueprint_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        self.blueprint_editor = QPlainTextEdit()
        self.blueprint_editor.setObjectName("blueprint-editor")
        self.blueprint_editor.setPlaceholderText(
            "# YAML Blueprint\n"
            "# Map package managers to their lists of desired packages.\n"
            "# Example:\n"
            "# Flatpak:\n"
            "#   - org.mozilla.firefox\n"
            "# DNF:\n"
            "#   - curl"
        )
        blueprint_splitter.addWidget(self.blueprint_editor)

        btn_widget = QWidget()
        btn_layout = QVBoxLayout(btn_widget)
        btn_layout.setContentsMargins(10, 0, 10, 0)
        btn_layout.setSpacing(10)

        self.btn_export_blueprint = QPushButton("Export Local Configuration")
        self.btn_load_blueprint = QPushButton("Load Blueprint File...")
        self.btn_save_blueprint = QPushButton("Save Blueprint File...")
        self.btn_sync_blueprint = QPushButton("Sync System to Blueprint")

        self.btn_export_blueprint.clicked.connect(self.export_local_configuration)
        self.btn_load_blueprint.clicked.connect(self.load_blueprint_file)
        self.btn_save_blueprint.clicked.connect(self.save_blueprint_file)
        self.btn_sync_blueprint.clicked.connect(self.sync_system_to_blueprint)

        btn_layout.addWidget(self.btn_export_blueprint)
        btn_layout.addWidget(self.btn_load_blueprint)
        btn_layout.addWidget(self.btn_save_blueprint)
        btn_layout.addWidget(self.btn_sync_blueprint)
        btn_layout.addStretch()

        blueprint_splitter.addWidget(btn_widget)
        blueprint_splitter.setSizes([550, 200])
        blueprints_layout.addWidget(blueprint_splitter)

        self.blueprint_status = QLabel("Ready")
        self.blueprint_status.setStyleSheet("color: #a6e3a1; font-weight: bold;")
        blueprints_layout.addWidget(self.blueprint_status)

        self.blueprint_progress = QProgressBar()
        self.blueprint_progress.setVisible(False)
        blueprints_layout.addWidget(self.blueprint_progress)

        self.stacked_widget.addWidget(blueprints_page)

        # PAGE 5: Package Managers
        managers_page = QWidget()
        managers_layout = QVBoxLayout(managers_page)
        managers_layout.setContentsMargins(20, 20, 20, 20)
        managers_layout.setSpacing(15)

        lbl_managers_title = QLabel("Manage Package Manager Drivers")
        lbl_managers_title.setObjectName("summary-label")
        managers_layout.addWidget(lbl_managers_title)

        lbl_managers_desc = QLabel("Browse which manager backend drivers are active on your system. You can install missing backends directly via DNF.")
        lbl_managers_desc.setObjectName("summary-label")
        lbl_managers_desc.setWordWrap(True)
        lbl_managers_desc.setStyleSheet("font-size: 13px; font-weight: normal; color: #a6adc8;")
        managers_layout.addWidget(lbl_managers_desc)

        self.managers_list = QListWidget()
        self.managers_list.setObjectName("updates-list")
        managers_layout.addWidget(self.managers_list)

        self.stacked_widget.addWidget(managers_page)

        # PAGE 6: Repositories
        repos_page = QWidget()
        repos_layout = QHBoxLayout(repos_page)
        repos_layout.setContentsMargins(0, 0, 0, 0)
        repos_layout.setSpacing(0)

        # Left panel: list of managers supporting repos
        repos_sidebar = QWidget()
        repos_sidebar.setObjectName("sidebar-panel")
        repos_sidebar.setFixedWidth(200)
        repos_sidebar_layout = QVBoxLayout(repos_sidebar)
        repos_sidebar_layout.setContentsMargins(12, 12, 12, 12)
        repos_sidebar_layout.setSpacing(10)

        lbl_repos_sidebar_title = QLabel("SOURCES")
        lbl_repos_sidebar_title.setObjectName("sidebar-title")
        repos_sidebar_layout.addWidget(lbl_repos_sidebar_title)

        self.repos_mgr_list = QListWidget()
        self.repos_mgr_list.setObjectName("nav-list")
        self.repos_mgr_list.currentRowChanged.connect(self.load_repos_for_selected_manager)
        repos_sidebar_layout.addWidget(self.repos_mgr_list)

        repos_layout.addWidget(repos_sidebar)

        # Right panel: repos list + add form
        repos_main = QWidget()
        repos_main_layout = QVBoxLayout(repos_main)
        repos_main_layout.setContentsMargins(20, 20, 20, 20)
        repos_main_layout.setSpacing(15)

        lbl_repos_main_title = QLabel("Repository Configuration")
        lbl_repos_main_title.setObjectName("summary-label")
        repos_main_layout.addWidget(lbl_repos_main_title)

        self.repos_list_widget = QListWidget()
        self.repos_list_widget.setObjectName("updates-list")
        repos_main_layout.addWidget(self.repos_list_widget)

        # Add Repo Form
        add_repo_widget = QWidget()
        add_repo_layout = QHBoxLayout(add_repo_widget)
        add_repo_layout.setContentsMargins(0, 0, 0, 0)
        add_repo_layout.setSpacing(10)

        self.txt_add_repo = QLineEdit()
        self.txt_add_repo.setPlaceholderText("Enter repository URL, filepath, or COPR group/project...")
        self.txt_add_repo.setObjectName("search-bar")
        add_repo_layout.addWidget(self.txt_add_repo, stretch=1)

        self.btn_add_repo = QPushButton("Add Source")
        self.btn_add_repo.clicked.connect(self.add_repository_source)
        add_repo_layout.addWidget(self.btn_add_repo)

        repos_main_layout.addWidget(add_repo_widget)
        repos_layout.addWidget(repos_main)

        self.stacked_widget.addWidget(repos_page)

        # PAGE 7: History Page
        history_page = QWidget()
        history_layout = QVBoxLayout(history_page)
        history_layout.setContentsMargins(20, 20, 20, 20)
        history_layout.setSpacing(15)

        lbl_history_title = QLabel("Update Execution History")
        lbl_history_title.setObjectName("summary-label")
        history_layout.addWidget(lbl_history_title)

        self.history_list = QListWidget()
        self.history_list.setObjectName("updates-list")
        history_layout.addWidget(self.history_list)

        self.stacked_widget.addWidget(history_page)

        # PAGE 8: Settings Page (rebuilt from the stores each time it's shown)
        settings_scroll = QScrollArea()
        settings_scroll.setObjectName("settings-scroll")
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        settings_inner = QWidget()
        settings_inner.setObjectName("settings-inner")
        self.settings_layout = QVBoxLayout(settings_inner)
        self.settings_layout.setContentsMargins(20, 20, 20, 20)
        self.settings_layout.setSpacing(10)
        settings_scroll.setWidget(settings_inner)
        self.stacked_widget.addWidget(settings_scroll)

        # PAGE 9: Debug Console — live stream of all package-manager and repo-sync output.
        debug_page = QWidget()
        debug_layout = QVBoxLayout(debug_page)
        debug_layout.setContentsMargins(20, 20, 20, 20)
        debug_layout.setSpacing(15)

        lbl_debug_title = QLabel("Debug Console")
        lbl_debug_title.setObjectName("summary-label")
        debug_layout.addWidget(lbl_debug_title)

        lbl_debug_desc = QLabel("Live stream of every package-manager command, upgrade, repo sync, "
                                "and scan operation. Use run.py --debug <command> from the terminal "
                                "to see the same stream on stderr.")
        lbl_debug_desc.setObjectName("summary-label")
        lbl_debug_desc.setWordWrap(True)
        lbl_debug_desc.setStyleSheet("font-size: 13px; font-weight: normal; color: #a6adc8;")
        debug_layout.addWidget(lbl_debug_desc)

        self.debug_console = QTextEdit()
        self.debug_console.setReadOnly(True)
        self.debug_console.setObjectName("console-output")
        debug_layout.addWidget(self.debug_console)

        btn_debug_clear = QPushButton("Clear")
        btn_debug_clear.clicked.connect(self.debug_console.clear)
        debug_layout.addWidget(btn_debug_clear)

        self.stacked_widget.addWidget(debug_page)

        splitter.addWidget(self.stacked_widget)

        splitter.setSizes([250, 750])

    def _build_terminal_overlay(self, parent_layout) -> None:
        """Build a collapsible terminal overlay at the bottom of the main window.

        Shows live log output from ExecutionWorker during upgrades and store installs.
        Hidden by default; auto-shows when an operation starts.
        """
        self.terminal_overlay = QFrame()
        self.terminal_overlay.setObjectName("terminal-overlay")
        self.terminal_overlay.setFixedHeight(200)
        self.terminal_overlay.hide()
        overlay_layout = QVBoxLayout(self.terminal_overlay)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        overlay_layout.setSpacing(0)

        # Title bar
        title_bar = QWidget()
        title_bar.setObjectName("terminal-titlebar")
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(10, 4, 10, 4)
        title_layout.setSpacing(8)

        lbl_term_title = QLabel("⚡ Live Output")
        lbl_term_title.setObjectName("terminal-title")
        title_layout.addWidget(lbl_term_title)

        self._terminal_title_label = lbl_term_title

        title_layout.addStretch()

        btn_term_clear = QPushButton("Clear")
        btn_term_clear.setAccessibleName("Clear terminal output")
        btn_term_clear.setToolTip("Clear the terminal output")
        btn_term_clear.clicked.connect(self._clear_terminal)
        btn_term_clear.setFixedWidth(70)
        title_layout.addWidget(btn_term_clear)

        btn_term_close = QPushButton("✕")
        btn_term_close.setAccessibleName("Close terminal overlay")
        btn_term_close.setToolTip("Close terminal overlay")
        btn_term_close.clicked.connect(self.terminal_overlay.hide)
        btn_term_close.setFixedWidth(30)
        title_layout.addWidget(btn_term_close)

        overlay_layout.addWidget(title_bar)

        # Log output area
        self.terminal_output = QTextEdit()
        self.terminal_output.setReadOnly(True)
        self.terminal_output.setObjectName("terminal-output")
        overlay_layout.addWidget(self.terminal_output)

        parent_layout.addWidget(self.terminal_overlay)

    def _clear_terminal(self) -> None:
        self.terminal_output.clear()

    def _show_terminal(self, title: str = "⚡ Live Output") -> None:
        """Show the terminal overlay with an optional title."""
        self._terminal_title_label.setText(title)
        self.terminal_overlay.show()
        self.terminal_output.verticalScrollBar().setValue(
            self.terminal_output.verticalScrollBar().maximum()
        )

    def _append_terminal(self, text: str) -> None:
        """Append a line to the terminal overlay and auto-scroll."""
        self.terminal_output.append(text)
        self.terminal_output.verticalScrollBar().setValue(
            self.terminal_output.verticalScrollBar().maximum()
        )

    def apply_theme(self):
        """Apply a premium dark-mode theme stylesheet."""
        self.setStyleSheet(self._scale_qss("""
            QMainWindow {
                background-color: #1e1e2e;
            }
            QWidget {
                color: #cdd6f4;
                font-family: 'Outfit', 'Inter', 'Segoe UI', sans-serif;
                font-size: 13px;
            }
            QDialog, QMessageBox {
                background-color: #1e1e2e;
            }
            QMessageBox QLabel {
                color: #cdd6f4;
            }
            QPlainTextEdit {
                background-color: #11111b;
                border: 1px solid #313244;
                border-radius: 6px;
                color: #cdd6f4;
            }
            QTabWidget::pane {
                border: 1px solid #313244;
                border-radius: 6px;
                top: -1px;
            }
            QTabBar::tab {
                background-color: #181825;
                color: #a6adc8;
                border: 1px solid #313244;
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                padding: 6px 14px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: #313244;
                color: #cdd6f4;
                font-weight: bold;
            }
            QLabel#review-error {
                color: #f38ba8;
                font-weight: bold;
            }
            QLabel#review-url {
                color: #7f849c;
                font-size: 11px;
            }
            QWidget#sidebar-panel {
                background-color: #11111b;
                border-right: 1px solid #313244;
            }
            QWidget#sidebar-banner {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #89b4fa, stop:1 #cba6f7);
                border-radius: 8px;
                margin-bottom: 5px;
            }
            QLabel#banner-title {
                font-size: 16px;
                font-weight: 800;
                color: #11111b;
                letter-spacing: 2px;
            }
            QLabel#banner-subtitle {
                font-size: 10px;
                font-weight: 600;
                color: #313244;
            }
            QLabel#brand-name {
                font-size: 17px;
                font-weight: 700;
                color: #cdd6f4;
            }
            QLabel#brand-subtitle {
                font-size: 12px;
                color: #a6adc8;
            }
            QFrame#status-card {
                background-color: #181825;
                border: 1px solid #313244;
                border-radius: 10px;
            }
            QFrame#status-card QLabel {
                background: transparent;
            }
            QLabel#status-count {
                font-size: 30px;
                font-weight: 800;
                color: #cdd6f4;
            }
            QLabel#status-checked {
                font-size: 11px;
                color: #7f849c;
            }
            QToolButton#btn-update-primary {
                background-color: #89b4fa;
                color: #11111b;
                border: none;
                border-radius: 6px;
                padding: 10px 18px;
                padding-right: 30px;
                font-weight: bold;
            }
            QToolButton#btn-update-primary:hover {
                background-color: #b4befe;
            }
            QToolButton#btn-update-primary:disabled {
                background-color: #313244;
                color: #585b70;
            }
            QToolButton#btn-update-primary::menu-button {
                border-left: 1px solid #11111b;
                width: 24px;
            }
            QCheckBox#select-all {
                color: #a6adc8;
                spacing: 8px;
            }
            QFrame#selection-bar {
                background-color: #313244;
                border-radius: 10px;
            }
            QFrame#selection-bar QLabel {
                background: transparent;
            }
            QLabel#selection-count {
                font-weight: bold;
                color: #cdd6f4;
            }
            QLabel#selection-admin {
                color: #a6adc8;
            }
            QLabel#selection-admin[warn="true"] {
                color: #f9e2af;
                font-weight: bold;
            }
            QPushButton#selection-clear {
                background-color: transparent;
                color: #a6adc8;
            }
            QPushButton#selection-clear:hover {
                background-color: #45475a;
                color: #cdd6f4;
            }
            QWidget#group-header {
                background-color: #11111b;
                border: 1px solid #313244;
                border-radius: 8px;
            }
            QWidget#group-header[failed="true"] {
                background-color: #2a1c26;
                border-color: #5c2d3e;
            }
            QWidget#group-header QLabel {
                background: transparent;
                border: none;
            }
            QLabel#group-name {
                font-size: 14px;
                font-weight: bold;
                color: #cdd6f4;
            }
            QLabel#group-state, QLabel#group-when {
                font-size: 12px;
                color: #a6adc8;
            }
            QLabel#group-state-failed {
                font-size: 12px;
                font-weight: bold;
                color: #f38ba8;
            }
            QLabel#group-admin {
                font-size: 12px;
                color: #f9e2af;
            }
            QLabel#group-footer {
                font-size: 12px;
                color: #7f849c;
                padding: 8px 12px;
            }
            QPushButton#group-retry {
                background-color: transparent;
                color: #f38ba8;
                border: 1px solid #f38ba8;
                padding: 4px 12px;
            }
            QPushButton#group-retry:hover {
                background-color: #f38ba8;
                color: #11111b;
            }
            QLabel#nav-section {
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 1px;
                color: #7f849c;
                padding: 12px 10px 4px 10px;
            }
            QPushButton#nav-button {
                background-color: transparent;
                color: #a6adc8;
                font-weight: normal;
                text-align: left;
                padding: 9px 10px;
                border-radius: 8px;
            }
            QPushButton#nav-button:hover {
                background-color: #181825;
                color: #cdd6f4;
            }
            QPushButton#nav-button:checked {
                background-color: #313244;
                color: #cdd6f4;
                font-weight: bold;
            }
            QToolButton#rail-button {
                background-color: transparent;
                color: #a6adc8;
                border: none;
                border-radius: 10px;
                padding: 6px 2px;
                font-size: 11px;
            }
            QToolButton#rail-button:hover {
                background-color: #181825;
                color: #cdd6f4;
            }
            QToolButton#rail-button:checked {
                background-color: #313244;
                color: #cdd6f4;
                font-weight: bold;
            }
            QLabel#sidebar-title {
                font-weight: bold;
                color: #89b4fa;
                font-size: 11px;
                text-transform: uppercase;
                margin-top: 10px;
                margin-bottom: 2px;
                letter-spacing: 0.5px;
            }
            QLabel#summary-label {
                font-size: 16px;
                font-weight: bold;
                color: #cdd6f4;
            }
            QLineEdit#search-bar {
                background-color: #11111b;
                border: 1px solid #313244;
                border-radius: 6px;
                padding: 8px 12px;
                color: #cdd6f4;
            }
            QLineEdit#search-bar:focus {
                border-color: #89b4fa;
            }
            QListWidget#nav-list, QListWidget#status-list {
                background: transparent;
                border: none;
            }
            QListWidget#nav-list::item {
                padding: 11px 14px;
                border-radius: 8px;
                margin-bottom: 4px;
                color: #a6adc8;
            }
            QListWidget#nav-list::item:selected {
                background-color: #313244;
                color: #89b4fa;
                font-weight: bold;
                border-left: 3px solid #89b4fa;
            }
            QListWidget#nav-list::item:hover:!selected {
                background-color: #181825;
                color: #cdd6f4;
            }
            QWidget#nav-item-row {
                background: transparent;
            }
            QListWidget#status-list::item {
                background-color: #181825;
                border: 1px solid #313244;
                padding: 8px 10px;
                border-radius: 6px;
                margin-bottom: 4px;
                color: #cdd6f4;
            }
            QListWidget#updates-list {
                background: transparent;
                border: none;
            }
            QListWidget#updates-list::item {
                background: transparent;
                padding: 0px;
                margin-bottom: 8px;
                border: none;
            }
            QListWidget#updates-list::item:selected {
                background: transparent;
                border: none;
            }
            QWidget#update-item-card, QWidget#store-item-card {
                background-color: #181825;
                border: 1px solid #313244;
                border-radius: 8px;
            }
            QWidget#update-item-card:hover, QWidget#store-item-card:hover {
                background-color: #1e1e2e;
                border-color: #89b4fa;
            }
            QPushButton {
                background-color: #89b4fa;
                color: #11111b;
                border: none;
                border-radius: 6px;
                padding: 10px 18px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #b4befe;
            }
            QPushButton:disabled {
                background-color: #313244;
                color: #585b70;
            }
            QPushButton#btn-scan {
                background-color: #313244;
                color: #cdd6f4;
            }
            QPushButton#btn-scan:hover {
                background-color: #45475a;
            }
            QTextEdit#console-output {
                background-color: #11111b;
                border: 1px solid #313244;
                border-radius: 8px;
                font-family: 'Fira Code', 'Courier New', monospace;
                color: #a6e3a1;
                font-size: 12px;
                padding: 10px;
            }
            QFrame#terminal-overlay {
                background-color: #11111b;
                border-top: 1px solid #313244;
            }
            QWidget#terminal-titlebar {
                background-color: #181825;
                border-bottom: 1px solid #313244;
            }
            QLabel#terminal-title {
                color: #a6adc8;
                font-weight: bold;
                font-size: 12px;
            }
            QWidget#terminal-titlebar QPushButton {
                background-color: #313244;
                color: #a6adc8;
                border: none;
                border-radius: 4px;
                padding: 3px 10px;
                font-size: 11px;
                font-weight: normal;
            }
            QWidget#terminal-titlebar QPushButton:hover {
                background-color: #45475a;
                color: #cdd6f4;
            }
            QTextEdit#terminal-output {
                background-color: #11111b;
                border: none;
                font-family: 'Fira Code', 'Courier New', monospace;
                color: #a6e3a1;
                font-size: 12px;
                padding: 6px;
            }
            QPlainTextEdit#blueprint-editor {
                background-color: #11111b;
                border: 1px solid #313244;
                border-radius: 8px;
                font-family: 'Fira Code', 'Courier New', monospace;
                color: #cdd6f4;
                font-size: 13px;
                padding: 10px;
            }
            QProgressBar {
                border: 1px solid #313244;
                border-radius: 6px;
                background-color: #11111b;
                text-align: center;
                color: #ffffff;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #89b4fa;
                border-radius: 5px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 1px solid #313244;
                border-radius: 4px;
                background-color: #11111b;
            }
            QCheckBox::indicator:checked {
                background-color: #89b4fa;
            }
            QCheckBox::indicator:indeterminate {
                background-color: #45475a;
                border-color: #89b4fa;
            }
            QSpinBox {
                background-color: #11111b;
                color: #cdd6f4;
                border: 1px solid #313244;
                border-radius: 6px;
                min-width: 80px;
            }
            QScrollArea#settings-scroll, QWidget#settings-inner {
                background-color: #1e1e2e;
            }
            QWidget#settings-entry {
                background-color: #181825;
                border-radius: 8px;
            }
            QSplitter::handle {
                background-color: #313244;
            }
            QSplitter::handle:horizontal {
                width: 1px;
            }
            QSplitter::handle:vertical {
                height: 1px;
            }
            /* Custom ScrollBar Styling */
            QScrollBar:vertical {
                border: none;
                background: #11111b;
                width: 8px;
                margin: 0px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #45475a;
                min-height: 20px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #585b70;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                border: none;
                background: none;
            }
            QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical {
                background: none;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
            QScrollBar:horizontal {
                border: none;
                background: #11111b;
                height: 8px;
                margin: 0px;
                border-radius: 4px;
            }
            QScrollBar::handle:horizontal {
                background: #45475a;
                min-width: 20px;
                border-radius: 4px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #585b70;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                border: none;
                background: none;
            }
            QMenu {
                background-color: #181825;
                border: 1px solid #313244;
                border-radius: 6px;
                padding: 4px 0px;
            }
            QMenu::item {
                background-color: transparent;
                color: #cdd6f4;
                padding: 6px 24px;
            }
            QMenu::item:selected {
                background-color: #313244;
                color: #89b4fa;
            }
            QMenu::item:disabled {
                color: #585b70;
            }
            QMenu::separator {
                height: 1px;
                background-color: #313244;
                margin: 4px 8px;
            }
            QComboBox {
                background-color: #11111b;
                border: 1px solid #313244;
                border-radius: 6px;
                padding: 6px 12px;
                color: #cdd6f4;
            }
            QComboBox:hover {
                border-color: #89b4fa;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 6px solid #a6adc8;
                margin-right: 8px;
            }
            QComboBox QAbstractItemView {
                background-color: #181825;
                border: 1px solid #313244;
                border-radius: 6px;
                padding: 4px 0px;
                selection-background-color: #313244;
                selection-color: #89b4fa;
                outline: none;
            }
            QComboBox QAbstractItemView::item {
                background-color: transparent;
                color: #cdd6f4;
                padding: 6px 16px;
                border: none;
            }
            QComboBox QAbstractItemView::item:selected {
                background-color: #313244;
                color: #89b4fa;
            }
            QComboBox QAbstractItemView::item:hover:!selected {
                background-color: #1e1e2e;
                color: #cdd6f4;
            }
            QToolTip {
                background-color: #181825;
                color: #cdd6f4;
                border: 1px solid #313244;
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 12px;
            }
        """))

    def _create_nav_row(self, icon_name: str, text: str) -> tuple[QWidget, QLabel, QLabel]:
        """Build a nav-list row with an icon, label, and a right-aligned pending-count badge.

        setItemWidget() replaces the QListWidgetItem's own icon/text painting entirely, so the
        selected/hover text-color rules in the ::item QSS no longer reach this row — the label's
        selected-state color is instead toggled manually from change_page().

        Returns:
            tuple[QWidget, QLabel, QLabel]: The row widget, its text label, and its badge label
                (badge starts hidden; caller shows/updates it via setText()/setVisible()).
        """
        row = QWidget()
        row.setObjectName("nav-item-row")
        layout = QHBoxLayout(row)
        # Deliberately zero margins: the ::item padding/margin-bottom QSS rule is subtracted
        # from whatever sizeHint the *item* reports to size this widget's content area, so
        # adding padding here too would double it up. The caller sizes the item itself (see
        # setup_ui, where item_updates borrows a plain-text row's sizeHint) to match natively
        # padded rows instead.
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        icon_label = QLabel()
        icon_label.setPixmap(QIcon.fromTheme(icon_name).pixmap(16, 16))
        layout.addWidget(icon_label)

        text_label = QLabel(text)
        text_label.setObjectName("nav-item-text")
        layout.addWidget(text_label)

        layout.addStretch()

        badge_label = QLabel("")
        badge_label.setObjectName("nav-badge")
        badge_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge_label.setVisible(False)
        layout.addWidget(badge_label)

        self._style_nav_row_text(text_label, selected=False)
        return row, text_label, badge_label

    def _style_nav_row_text(self, label: QLabel, selected: bool) -> None:
        """Match a nav row's text-label color/weight to the ::item:selected QSS rule by hand."""
        if selected:
            label.setStyleSheet("color: #89b4fa; font-weight: bold; background: transparent;")
        else:
            label.setStyleSheet("color: #a6adc8; font-weight: normal; background: transparent;")

    def update_updates_badge(self) -> None:
        """Refresh the pending-updates count badge on the sidebar's "System Updates" row."""
        total = sum(len(u) for u in self.updates_cache.values())
        style = ("background-color: #89b4fa; color: #11111b; border-radius: 9px; "
                 "padding: 1px 7px; font-weight: bold; font-size: 11px;")
        if total > 0:
            self.nav_updates_badge.setText(str(total))
            self.nav_updates_badge.setStyleSheet(style)
            self.nav_updates_badge.setVisible(True)
        else:
            self.nav_updates_badge.setVisible(False)
        for view in (self.nav_grouped, self.nav_rail):
            view.set_badge(PAGE_UPDATES, str(total) if total else "", style)
        self.refresh_sidebar_status()

    def update_version_check_badge(self, count: int) -> None:
        """Refresh the version-check suggestions count badge."""
        style = ("background-color: #f9e2af; color: #11111b; border-radius: 9px; "
                 "padding: 1px 7px; font-weight: bold; font-size: 11px;")
        if count > 0:
            self.nav_version_check_badge.setText(str(count))
            self.nav_version_check_badge.setStyleSheet(style)
            self.nav_version_check_badge.setVisible(True)
        else:
            self.nav_version_check_badge.setVisible(False)
        for view in (self.nav_grouped, self.nav_rail):
            view.set_badge(PAGE_VERSION_CHECK, str(count) if count > 0 else "", style)

    def _select_theme(self) -> None:
        """Make the Settings theme (resolving "Follow system") the active one."""
        from app.core.settings_store import get_settings
        settings = get_settings()
        key = themes.resolve(settings.get("ui.theme", themes.DEFAULT_THEME), theme_qt.system_is_dark(),
                             settings.get("ui.theme_dark", themes.DEFAULT_DARK),
                             settings.get("ui.theme_light", themes.DEFAULT_LIGHT))
        themes.set_active(key, settings.get("ui.accent"))

    def apply_appearance(self) -> None:
        """Switch theme/accent live: restyle the window, every existing widget, and the lists."""
        self._select_theme()
        self.apply_touch_mode()  # re-applies the main stylesheet (and rebuilds the update list)
        self.theme_filter.retheme_all()
        self.refresh_sidebar_status()
        self.apply_window_icon()

    def apply_window_icon(self) -> None:
        """Recolour the app icon for the active theme: window, taskbar, and sidebar headers."""
        icon = app_icon()
        QApplication.setWindowIcon(icon)
        self.setWindowIcon(icon)
        self.header_brand.icon.setPixmap(icon.pixmap(36, 36))
        self.header_status.icon.setPixmap(icon.pixmap(26, 26))
        self.rail_mark.setPixmap(icon.pixmap(40, 40))

    def tray_state(self) -> str:
        if self.scan_in_progress or self.active_operation is not None:
            return "updating"
        if self.scan_errors or self.upgrade_failures:
            return "error"
        if any(self.updates_cache.values()):
            return "updates"
        return "idle"

    def refresh_tray_icon(self) -> None:
        """Show the tray state (idle / updates waiting / updating / failed) in the tray icon."""
        if self.tray is None:
            return
        state = self.tray_state()
        if state != getattr(self, "_tray_icon_state", None):
            self._tray_icon_state = state
            self.tray.setIcon(tray_icon(state, theme_qt.system_is_dark()))

    def _on_system_scheme_changed(self, *_args) -> None:
        from app.core.settings_store import get_settings
        if get_settings().get("ui.theme", themes.DEFAULT_THEME) == themes.SYSTEM:
            self.apply_appearance()

    def _sync_nav_views(self, page: int) -> None:
        """Mirror nav_list's current row onto the grouped and rail views."""
        for view in (self.nav_grouped, self.nav_rail):
            view.set_current(page)

    def refresh_sidebar_status(self) -> None:
        """Update the brand subtitle and the status card from the latest scan state."""
        from app.core.distro import get_distro_name
        count = len(self.managers)
        parts = [get_distro_name()]
        if count:
            parts.append(f"{count} manager{'' if count == 1 else 's'}")
        self.header_brand.set_subtitle(" · ".join(p for p in parts if p))
        counts = {name: len(pkgs) for name, pkgs in self.updates_cache.items()}
        self.header_status.update_status(counts, self.scan_in_progress, self.last_scan_at)
        self.refresh_tray_icon()

    def apply_sidebar_style(self) -> None:
        """Lay the sidebar out for the header and navigation styles saved in Settings.

        Safe to call live: widgets are only re-slotted and shown/hidden, never rebuilt, so
        scan state, badges, the filter text, and the current page all carry over.
        """
        from app.core.settings_store import get_settings
        settings = get_settings()
        header = settings.get("ui.sidebar_header", DEFAULT_HEADER_STYLE)
        nav = settings.get("ui.sidebar_nav", DEFAULT_NAV_STYLE)
        header = header if header in HEADER_STYLES else DEFAULT_HEADER_STYLE
        nav = nav if nav in NAV_STYLES else DEFAULT_NAV_STYLE
        was_rail = self.sidebar_nav_style == "rail"
        self.sidebar_header_style, self.sidebar_nav_style = header, nav
        rail = nav == "rail"

        layout = self.sidebar_layout
        while layout.count():
            layout.takeAt(0)  # widgets stay parented to the sidebar; only their slots go
        for widget in (self.header_banner, self.header_brand, self.header_status, self.rail_mark,
                       self.nav_list, self.nav_grouped, self.nav_rail,
                       self.sources_line, self.lbl_sources, self.status_list):
            widget.hide()
        self.header_status.button_slot.removeWidget(self.btn_scan)
        self.updates_header.removeWidget(self.search_bar)

        if rail:
            # Too narrow for a header, filter box or button labels: show the app mark, move the
            # filter onto the Updates page, and turn the two actions into icon buttons.
            layout.setContentsMargins(6, 12, 6, 12)
            shown = [self.rail_mark, self.nav_rail]
            self.updates_header.insertWidget(1, self.search_bar)
            self.search_bar.setMaximumWidth(self._px(260))
            self.sidebar_widget.setFixedWidth(RailNav.WIDTH + 12)
        else:
            layout.setContentsMargins(12, 12, 12, 12)
            header_widget = {"banner": self.header_banner, "brand": self.header_brand,
                             "status": self.header_status}[header]
            shown = [header_widget, self.search_bar,
                     self.nav_grouped if nav == "grouped" else self.nav_list]
            # The status card already shows per-manager counts, so the list would repeat it.
            if header != "status":
                shown += [self.sources_line, self.lbl_sources, self.status_list]
            self.search_bar.setMaximumWidth(16777215)
            self.sidebar_widget.setMinimumWidth(0)
            self.sidebar_widget.setMaximumWidth(16777215)
            if was_rail:
                sizes = self.main_splitter.sizes()
                if sizes:
                    self.main_splitter.setSizes([250, max(sum(sizes) - 250, 400)])
        # The grouped view stretches to pin Settings to the bottom; when the status list is
        # below it, let the list take the spare height instead.
        status_list_shown = self.status_list in shown
        self.nav_grouped.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Maximum if status_list_shown else QSizePolicy.Policy.Preferred)
        for widget in shown:
            layout.addWidget(widget)
            widget.show()

        if not rail and header == "status":
            self.header_status.button_slot.addWidget(self.btn_scan)
        else:
            layout.addWidget(self.btn_scan)
        layout.addWidget(self.btn_refresh_repos)
        self.search_bar.show()

        reload_icon = QIcon.fromTheme(
            "view-refresh", self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        sync_icon = QIcon.fromTheme(
            "emblem-synchronizing", self.style().standardIcon(QStyle.StandardPixmap.SP_DriveNetIcon))
        for button, text, icon in ((self.btn_scan, "Check for Updates", reload_icon),
                                   (self.btn_refresh_repos, "Sync Repositories", sync_icon)):
            button.setText("" if rail else text)
            button.setIcon(icon if rail else QIcon())
            button.setToolTip(text if rail else "")
        self.refresh_sidebar_status()

    def change_page(self, index: int):
        if index >= 0:
            # Leaving the Debug Console page: unsubscribe from the debug stream.
            if self.stacked_widget.currentIndex() == PAGE_DEBUG:
                self._leave_debug_page()

            self.stacked_widget.setCurrentIndex(index)
            self._style_nav_row_text(self.nav_updates_label, selected=(index == PAGE_UPDATES))
            if index == PAGE_VERSION_CHECK:
                self._style_nav_row_text(self.nav_version_check_label, selected=True)
            else:
                self._style_nav_row_text(self.nav_version_check_label, selected=False)
            if index == PAGE_MANAGERS:
                self.populate_managers_list()
            elif index == PAGE_REPOS:
                self.populate_repos_managers()
            elif index == PAGE_HISTORY:
                self.populate_history_page()
            elif index == PAGE_SETTINGS:
                self.populate_settings_page()
            elif index == PAGE_DEBUG:
                self._enter_debug_page()

    def _enter_debug_page(self):
        """Subscribe to the debug log stream when the Debug Console page is shown."""
        if not getattr(self, "_debug_subscribed", False):
            from app.core.debug_log import debug_log_signal, HAVE_QT, debug_log
            if HAVE_QT and debug_log_signal is not None:
                debug_log_signal.connect(self._append_debug_line)
            self._debug_subscribed = True
        # Dump current state for AI tools
        from app.core.debug_log import debug_log as _dl
        _dl.dump_state({
            "managers": list(self.managers.keys()),
            "updates_cache": {k: len(v) for k, v in self.updates_cache.items()},
            "scan_errors": self.scan_errors,
            "selected_updates": {k: list(v) for k, v in self.selected_updates.items()},
        })

    def _leave_debug_page(self):
        """Unsubscribe from the debug log stream when leaving the Debug Console page."""
        if getattr(self, "_debug_subscribed", False):
            from app.core.debug_log import debug_log_signal, HAVE_QT
            if HAVE_QT and debug_log_signal is not None:
                debug_log_signal.disconnect(self._append_debug_line)
            self._debug_subscribed = False

    def _append_debug_line(self, message: str) -> None:
        """Append a debug message to the Debug Console text area."""
        self.debug_console.append(message)
        self.debug_console.verticalScrollBar().setValue(
            self.debug_console.verticalScrollBar().maximum()
        )

    def run_version_check(self) -> None:
        """Run the cross-manager version check scan in a worker thread."""
        self.version_check_tree.clear()
        self.version_check_progress.setVisible(True)
        self.version_check_progress.setRange(0, 0)  # Indeterminate
        self.btn_version_check.setEnabled(False)
        self.lbl_version_check_summary.setText("Scanning for cross-manager version differences...")

        worker = VersionCheckWorker(self.managers)
        worker.log_signal.connect(self.log)
        worker.suggestions_signal.connect(self.handle_version_check_results)
        worker.error_signal.connect(self.handle_version_check_error)
        worker.finished.connect(self._on_version_check_finished)
        self.active_workers.append(worker)
        worker.start()

    @Slot(list, dict)
    def handle_version_check_results(self, suggestions: list[dict[str, Any]], manager_status: dict) -> None:
        """Display version check suggestions in the tree."""
        self.version_check_tree.clear()
        if not suggestions:
            item = QTreeWidgetItem(["✅ No packages found with newer versions on other managers.", "", "", "", ""])
            item.setForeground(0, Qt.GlobalColor.green)
            self.version_check_tree.addTopLevelItem(item)
            self.update_version_check_badge(0)
            self.lbl_version_check_summary.setText("No cross-manager version differences found.")
            scanned = [name for name, status in manager_status.items() if status.get("ok")]
            if scanned:
                self.lbl_version_check_summary.setText(f"Scanned {len(scanned)} managers. No cross-manager version differences found.")
            return

        self.update_version_check_badge(len(suggestions))
        self.lbl_version_check_summary.setText(f"Found {len(suggestions)} package(s) with a newer version on another manager:")

        for s in suggestions:
            newest = s["newest"]
            installed_str = ", ".join(f"{m}={v}" for m, v in s["installed"].items())
            note = s.get("note", "")
            
            # Top-level item
            top_item = QTreeWidgetItem([
                s["package"],
                newest["manager"],
                newest["version"],
                installed_str,
                note
            ])
            top_item.setToolTip(0, "Double-click for details")
            self.version_check_tree.addTopLevelItem(top_item)
            
            # Child items for each installed version (expandable)
            for mgr, ver in s["installed"].items():
                child = QTreeWidgetItem(["", mgr, ver, "", ""])
                top_item.addChild(child)
            top_item.setExpanded(False)  # Collapsed by default

        self.version_check_tree.resizeColumnToContents(0)
        self.version_check_tree.resizeColumnToContents(1)
        self.version_check_tree.resizeColumnToContents(2)
        self.version_check_tree.resizeColumnToContents(4)

    def show_version_check_detail(self, item: QTreeWidgetItem, column: int) -> None:
        """Show detail dialog for a version check suggestion."""
        # Only show detail for top-level items (suggestions)
        if item.parent() is None:
            pkg = item.text(0)
            newest_mgr = item.text(1)
            newest_ver = item.text(2)
            installed = item.text(3)
            note = item.text(4)
            
            detail_text = f"<b>Package:</b> {pkg}<br/>"
            detail_text += f"<b>Newest:</b> {newest_mgr} {newest_ver}<br/>"
            detail_text += f"<b>Installed:</b> {installed}<br/>"
            if note:
                detail_text += f"<b>Note:</b> {note}<br/>"
            
            QMessageBox.information(self, f"Version Check: {pkg}", detail_text)

    @Slot(str)
    def handle_version_check_error(self, error: str) -> None:
        """Handle version check scan error."""
        self.log(f"❌ Version check scan failed: {error}")
        self.version_check_tree.clear()
        item = QTreeWidgetItem([f"❌ Scan failed: {error}", "", "", "", ""])
        item.setForeground(0, Qt.GlobalColor.red)
        self.version_check_tree.addTopLevelItem(item)
        self.update_version_check_badge(0)
        self.lbl_version_check_summary.setText("Version scan failed — see log for details.")

    def _on_version_check_finished(self) -> None:
        """Clean up after version check worker finishes."""
        self.version_check_progress.setVisible(False)
        self.btn_version_check.setEnabled(True)

    def populate_settings_page(self) -> None:
        """Rebuild the Settings page from the current stores. Every control saves immediately."""
        from app.core.ignore_store import IgnoreStore
        from app.core.settings_store import get_settings
        settings = get_settings()
        layout = self.settings_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        def heading(text: str, hint: str = "") -> None:
            lbl = QLabel(text)
            lbl.setObjectName("summary-label")
            layout.addSpacing(8)
            layout.addWidget(lbl)
            if hint:
                lbl_hint = QLabel(hint)
                lbl_hint.setWordWrap(True)
                lbl_hint.setStyleSheet("color: #a6adc8;")
                layout.addWidget(lbl_hint)

        def toggle(text: str, key: str, default: bool, on_change=None) -> None:
            box = QCheckBox(text)
            box.setChecked(bool(settings.get(key, default)))
            def changed(state, key=key):
                settings.set(key, state == Qt.CheckState.Checked.value)
                if on_change:
                    on_change()
            box.stateChanged.connect(changed)
            layout.addWidget(box)

        def entries(rows: list[tuple[str, Any]], empty: str, remove) -> None:
            if not rows:
                lbl = QLabel(empty)
                lbl.setStyleSheet("color: #6c7086; font-style: italic;")
                layout.addWidget(lbl)
            for text, key in rows:
                row = QWidget()
                row.setObjectName("settings-entry")
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(12, 4, 4, 4)
                row_layout.addWidget(QLabel(text), 1)
                btn = QPushButton("Remove")
                btn.setAccessibleName(f"Remove {text}")
                btn.clicked.connect(lambda _=False, k=key: (remove(k), self.populate_settings_page()))
                row_layout.addWidget(btn)
                layout.addWidget(row)

        heading("General")
        toggle("Check for updates when PolyGet opens", "ui.scan_on_launch", True)
        toggle("Show the exact command before running anything", "ui.confirm_commands", True)
        toggle("Touch mode — bigger buttons, rows and checkboxes", "ui.touch_mode", False,
               on_change=self.apply_touch_mode)

        scale_row = QWidget()
        scale_layout = QHBoxLayout(scale_row)
        scale_layout.setContentsMargins(0, 0, 0, 0)
        scale_layout.addWidget(QLabel("UI scale"))
        scale_spin = QSpinBox()
        scale_spin.setRange(75, 200)
        scale_spin.setSingleStep(5)
        scale_spin.setSuffix(" %")
        scale_spin.setValue(int(settings.get("ui.scale_percent", 100)))
        scale_spin.valueChanged.connect(
            lambda v: (settings.set("ui.scale_percent", v), self.apply_touch_mode()))
        scale_layout.addWidget(scale_spin)
        scale_layout.addStretch()
        layout.addWidget(scale_row)

        font_row = QWidget()
        font_layout = QHBoxLayout(font_row)
        font_layout.setContentsMargins(0, 0, 0, 0)
        font_layout.addWidget(QLabel("Font size"))
        font_spin = QSpinBox()
        font_spin.setRange(0, 32)
        font_spin.setSpecialValueText("default")
        font_spin.setSuffix(" px")
        font_spin.setValue(int(settings.get("ui.font_size", 0)))
        font_spin.valueChanged.connect(
            lambda v: (settings.set("ui.font_size", v), self.apply_touch_mode()))
        font_layout.addWidget(font_spin)
        font_layout.addStretch()
        layout.addWidget(font_row)

        heading("Theme", "Colours for the whole window (and the TUI next time it starts). "
                "Changes apply right away.")
        appearance_combos: dict[str, QComboBox] = {}

        def choice_row(text: str, key: str, options: list[tuple[str, Any]], default: Any) -> QComboBox:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            label = QLabel(text)
            label.setMinimumWidth(self._px(110))
            row_layout.addWidget(label)
            combo = QComboBox()
            combo.setAccessibleName(text)
            for option_label, value in options:
                combo.addItem(option_label, value)
            index = combo.findData(settings.get(key, default))
            combo.setCurrentIndex(index if index >= 0 else max(combo.findData(default), 0))
            combo.currentIndexChanged.connect(
                lambda _i, c=combo, k=key: (settings.set(k, c.currentData()), sync_appearance(),
                                            self.apply_appearance()))
            row_layout.addWidget(combo)
            row_layout.addStretch()
            layout.addWidget(row)
            appearance_combos[key] = combo
            return combo

        dark = [(t.name, k) for k, t in themes.THEMES.items() if not t.light]
        light = [(t.name, k) for k, t in themes.THEMES.items() if t.light]
        choice_row("Theme", "ui.theme",
                   [("Follow system (dark/light)", themes.SYSTEM)] + dark + [(f"{n} (light)", k) for n, k in light],
                   themes.DEFAULT_THEME)
        choice_row("   When dark", "ui.theme_dark", dark + light, themes.DEFAULT_DARK)
        choice_row("   When light", "ui.theme_light", light + dark, themes.DEFAULT_LIGHT)
        accent_combo = choice_row("Accent", "ui.accent",
                                  [("Theme default", None)] + [(r.capitalize(), r) for r in themes.ACCENT_ROLES if r != "blue"],
                                  None)
        for i in range(1, accent_combo.count()):
            role = accent_combo.itemData(i)
            swatch = QPixmap(14, 14)
            swatch.fill(QColor(themes.active().theme.roles[role]))
            accent_combo.setItemIcon(i, QIcon(swatch))

        def sync_appearance() -> None:
            follow = appearance_combos["ui.theme"].currentData() == themes.SYSTEM
            for key in ("ui.theme_dark", "ui.theme_light"):
                appearance_combos[key].parentWidget().setVisible(follow)
        sync_appearance()

        heading("Sidebar", "How the sidebar's header and page list look. Changes apply right away.")

        def style_choice(text: str, key: str, styles: dict[str, str], default: str) -> QComboBox:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(QLabel(text))
            combo = QComboBox()
            combo.setAccessibleName(text)
            for value, label in styles.items():
                combo.addItem(label, value)
            current = combo.findData(settings.get(key, default))
            combo.setCurrentIndex(current if current >= 0 else combo.findData(default))
            combo.currentIndexChanged.connect(
                lambda _i, c=combo, k=key: (settings.set(k, c.currentData()), self.apply_sidebar_style(),
                                            sync_header_enabled()))
            row_layout.addWidget(combo)
            row_layout.addStretch()
            layout.addWidget(row)
            return combo

        header_combo = style_choice("Header", "ui.sidebar_header", HEADER_STYLES, DEFAULT_HEADER_STYLE)
        nav_combo = style_choice("Navigation", "ui.sidebar_nav", NAV_STYLES, DEFAULT_NAV_STYLE)

        def sync_header_enabled() -> None:
            # The icon rail is too narrow for any header; it shows just the app icon.
            rail = nav_combo.currentData() == "rail"
            header_combo.setEnabled(not rail)
            header_combo.setToolTip("The icon rail shows only the app icon" if rail else "")
        sync_header_enabled()

        heading("Sudo password",
                "The GUI caches your sudo password in the system keyring so pkexec can "
                "fall back to sudo when no polkit agent is bound. Clear it here if you "
                "change your password or want to re-enter it next time.")
        from app.core import sudo_secret as _ss
        has_pw = _ss.available() and _ss.load() is not None
        btn_forget_pw = QPushButton("Forget saved sudo password")
        btn_forget_pw.setEnabled(has_pw)
        btn_forget_pw.setToolTip("Remove the stored sudo password from the keyring")
        btn_forget_pw.clicked.connect(lambda: self._forget_sudo_password(btn_forget_pw))
        layout.addWidget(btn_forget_pw)
        lbl_pw_status = QLabel(
            "Saved password: yes" if has_pw else "No saved password (keyring unavailable or none stored)."
        )
        lbl_pw_status.setObjectName("sudo-pw-status")
        lbl_pw_status.setStyleSheet("color: #6c7086; font-size: 11px;")
        layout.addWidget(lbl_pw_status)

        heading("Debug",
                "Write every package-manager command and result to a JSONL log file so "
                "AI coding assistants can read it. View live output in the Debug Console page.")
        from app.core import debug_log as _dl_mod
        debug_box = QCheckBox("Enable debug file logging")
        debug_box.setChecked(_dl_mod.debug_log.file_logging_enabled())
        def _toggle_debug(state):
            if state == Qt.CheckState.Checked.value:
                _dl_mod.debug_log.enable_file_logging()
            else:
                _dl_mod.debug_log.disable_file_logging()
        debug_box.stateChanged.connect(_toggle_debug)
        layout.addWidget(debug_box)
        lbl_debug_path = QLabel(f"Log file: {_dl_mod.debug_log.log_path}")
        lbl_debug_path.setStyleSheet("color: #6c7086; font-size: 11px;")
        layout.addWidget(lbl_debug_path)

        heading("Tray & background checks",
                "With the tray icon on, closing the window keeps PolyGet running so it can "
                "check for updates in the background and notify you.")
        toggle("Show tray icon", "tray.enabled", False, on_change=self.setup_tray)
        interval_row = QWidget()
        interval_layout = QHBoxLayout(interval_row)
        interval_layout.setContentsMargins(0, 0, 0, 0)
        interval_layout.addWidget(QLabel("Check for updates every"))
        spin = QSpinBox()
        spin.setRange(0, 168)
        spin.setSuffix(" h")
        spin.setSpecialValueText("never")
        spin.setValue(int(settings.get("tray.scan_interval_hours", 6)))
        spin.valueChanged.connect(lambda v: (settings.set("tray.scan_interval_hours", v), self.setup_tray()))
        interval_layout.addWidget(spin)
        interval_layout.addStretch()
        layout.addWidget(interval_row)
        toggle("Notify me when new updates are found", "tray.notify", True)
        autostart = QCheckBox("Start PolyGet in the tray when I log in")
        autostart.setChecked(_AUTOSTART_PATH.exists())
        autostart.stateChanged.connect(lambda state: set_autostart(state == Qt.CheckState.Checked.value))
        layout.addWidget(autostart)

        heading("Package managers", "Unchecked managers aren't scanned, synced, or upgraded "
                "(the CLI still uses them when you name them with -m).")
        disabled = set(settings.disabled_managers())
        for mgr in sorted(discover_managers(), key=lambda m: m.name.lower()):
            box = QCheckBox(f"{mgr.name}  ({mgr.category})")
            box.setChecked(mgr.name not in disabled)
            box.stateChanged.connect(
                lambda state, n=mgr.name: settings.set_manager_enabled(n, state == Qt.CheckState.Checked.value)
            )
            layout.addWidget(box)

        store = IgnoreStore()
        heading("Ignored packages", "Still listed, but never ticked automatically. Add one with "
                "an update's ⋯ button.")
        entries([(f"{pkg}  ({mgr})", (mgr, pkg)) for mgr, pkg in store.all_entries()],
                "Nothing ignored.", lambda k: store.remove(*k))

        heading("Skipped versions", "Hidden until a newer version comes out.")
        entries([(f"{pkg} {ver}  ({mgr})", (mgr, pkg)) for mgr, pkg, ver in settings.all_skipped()],
                "No skipped versions.", lambda k: settings.unskip_version(*k))

        heading("DNF: allow vendor change", "Upgraded even when dnf would skip them for coming "
                "from a different vendor.")
        vendor_ok = settings.get("dnf.allow_vendor_change", [])
        def _remove_vendor_allowance(k):
            settings.set("dnf.allow_vendor_change",
                         [p for p in settings.get("dnf.allow_vendor_change", []) if p != k])
            # Re-scan so the blocked flag is re-evaluated for the removed package
            if not self.scan_in_progress:
                self.scan_all()
        entries([(pkg, pkg) for pkg in vendor_ok], "No packages allowed.",
                _remove_vendor_allowance)
        layout.addStretch()

    def populate_history_page(self):
        self.history_list.clear()
        from app.core.history_store import load_history
        import time
        records = load_history()
        if not records:
            item = QListWidgetItem("No upgrade history recorded yet.")
            self.history_list.addItem(item)
            return
        for rec in records:
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(rec.get("timestamp", 0)))
            if not rec.get("verified", True):
                status = "❔ UNVERIFIED (pre-verification era)"
            else:
                status = "✅ SUCCESS" if rec.get("success") else "❌ FAILED"
                if rec.get("not_upgraded"):
                    status = "⚠ NOT UPGRADED (" + ", ".join(rec["not_upgraded"]) + ")"
            mgr = rec.get("manager", "Unknown")
            pkgs = ", ".join(rec.get("packages", []))
            item = QListWidgetItem(f"[{ts}] {status} - {mgr}: {pkgs}")
            self.history_list.addItem(item)

    def populate_repos_managers(self):
        self.repos_mgr_list.clear()
        from app.core.manager import discover_managers
        managers = discover_managers()
        self.repos_managers = [m for m in managers if getattr(m, "supports_repos", False)]
        for mgr in self.repos_managers:
            self.repos_mgr_list.addItem(mgr.name)
        if self.repos_mgr_list.count() > 0:
            self.repos_mgr_list.setCurrentRow(0)

    def load_repos_for_selected_manager(self, row: int):
        if row < 0 or row >= len(self.repos_managers):
            self.repos_list_widget.clear()
            self.repos_selected_manager = None
            return
        mgr = self.repos_managers[row]
        self.repos_list_widget.clear()

        self.repos_generation += 1
        generation = self.repos_generation
        self.repos_selected_manager = mgr.name

        worker = FetchReposWorker(mgr)
        worker.result_signal.connect(
            lambda repos, g=generation, m=mgr: self.display_repos_list(repos, m, g)
        )
        worker.error_signal.connect(lambda err: self.log(f"❌ Error fetching repositories: {err}"))
        self.active_workers.append(worker)
        worker.start()

    def display_repos_list(
        self, repos: list[dict[str, Any]], mgr: PackageManager, generation: int | None = None
    ):
        if generation is not None and (
            generation != self.repos_generation or mgr.name != self.repos_selected_manager
        ):
            return

        self.repos_list_widget.clear()
        for repo in repos:
            row_item = QListWidgetItem(self.repos_list_widget)
            row_item.setSizeHint(QSize(0, 65))
            row_widget = RepoItemWidget(repo)
            # Connect toggle and remove requests
            row_widget.toggle_requested.connect(lambda r_id, enable, m=mgr: self.toggle_repository_source(m, r_id, enable))
            row_widget.remove_requested.connect(lambda r_id, m=mgr: self.remove_repository_source(m, r_id))
            self.repos_list_widget.setItemWidget(row_item, row_widget)

    def toggle_repository_source(self, mgr: PackageManager, repo_id: str, enable: bool):
        if repo_id in self.repo_actions_in_flight:
            self.log(f"⚠️ An action on repository source '{repo_id}' is already in progress.")
            return

        if enable:
            # Re-enabling repo (special config-manager command for DNF, or flatpak remote-add)
            cmd = ["pkexec", "dnf", "config-manager", "--set-enabled", repo_id] if mgr.name == "DNF" else mgr.get_add_repo_command(repo_id)
        else:
            # Disabling repo
            cmd = mgr.get_remove_repo_command(repo_id)

        self.repo_actions_in_flight.add(repo_id)
        self.log(f"⚡ Toggling repository source: {repo_id} ({' '.join(cmd)})")
        self.nav_list.setCurrentRow(PAGE_CONSOLE)

        worker = ExecutionWorker(cmd)
        worker.log_signal.connect(self.log)
        worker.finished_signal.connect(lambda success: self.handle_repo_action_finished(success, repo_id, "modified"))
        worker.finished.connect(self._on_worker_finished)
        self.active_workers.append(worker)
        worker.start()

    def remove_repository_source(self, mgr: PackageManager, repo_id: str):
        if repo_id in self.repo_actions_in_flight:
            self.log(f"⚠️ An action on repository source '{repo_id}' is already in progress.")
            return

        cmd = mgr.get_remove_repo_command(repo_id)
        self.repo_actions_in_flight.add(repo_id)
        self.log(f"⚡ Removing repository source: {repo_id} ({' '.join(cmd)})")
        self.nav_list.setCurrentRow(PAGE_CONSOLE)

        worker = ExecutionWorker(cmd)
        worker.log_signal.connect(self.log)
        worker.finished_signal.connect(lambda success: self.handle_repo_action_finished(success, repo_id, "removed"))
        worker.finished.connect(self._on_worker_finished)
        self.active_workers.append(worker)
        worker.start()

    def add_repository_source(self):
        row = self.repos_mgr_list.currentRow()
        if row < 0 or row >= len(self.repos_managers):
            return
        mgr = self.repos_managers[row]
        repo_url = self.txt_add_repo.text().strip()
        if not repo_url:
            return

        if repo_url in self.repo_actions_in_flight:
            self.log(f"⚠️ An action on repository source '{repo_url}' is already in progress.")
            return

        cmd = mgr.get_add_repo_command(repo_url)
        self.repo_actions_in_flight.add(repo_url)
        self.log(f"⚡ Adding repository source: {repo_url} ({' '.join(cmd)})")
        self.txt_add_repo.clear()
        self.nav_list.setCurrentRow(PAGE_CONSOLE)

        worker = ExecutionWorker(cmd)
        worker.log_signal.connect(self.log)
        worker.finished_signal.connect(lambda success: self.handle_repo_action_finished(success, repo_url, "added"))
        worker.finished.connect(self._on_worker_finished)
        self.active_workers.append(worker)
        worker.start()

    def handle_repo_action_finished(self, success: bool, target: str, action: str):
        self.repo_actions_in_flight.discard(target)
        if success:
            self.log(f"✅ Successfully {action} repository source: {target}")
            self.load_repos_for_selected_manager(self.repos_mgr_list.currentRow())
        else:
            self.log(f"❌ Failed to perform action on repository source: {target}")

    def populate_managers_list(self):
        self.managers_list.clear()
        self._manager_widgets: dict[str, ManagerItemWidget] = {}
        from app.core.catalog import load_catalog
        entries = load_catalog()
        
        # Sort entries by name
        entries.sort(key=lambda e: e.name)
        
        for entry in entries:
            row_item = QListWidgetItem(self.managers_list)
            row_item.setSizeHint(QSize(0, 85))
            
            row_widget = ManagerItemWidget(entry)
            self._manager_widgets[entry.name] = row_widget
            row_widget.install_requested.connect(self.install_manager_backend)
            self.managers_list.setItemWidget(row_item, row_widget)
        
        # Fetch self-versions asynchronously and update labels when they arrive
        available = discover_managers()
        if available:
            worker = FetchManagerVersionsWorker(available)
            worker.result_signal.connect(self._apply_manager_versions)
            worker.finished.connect(self._on_worker_finished)
            self.active_workers.append(worker)
            worker.start()

    def _apply_manager_versions(self, versions: dict[str, str | None]):
        """Update each manager row with its self-reported version."""
        for name, version in versions.items():
            widget = self._manager_widgets.get(name)
            if widget is not None:
                widget.set_version(version)

    def install_manager_backend(self, entry: CatalogEntry):
        if entry.name in self.installing_managers:
            self.log(f"⚠️ Installation of {entry.name} is already in progress.")
            return

        cmd = entry.get_self_install_command()
        if not cmd:
            self.log(f"❌ Install command not found for {entry.name} on this distro family.")
            return

        self.installing_managers.add(entry.name)
        self.log(f"⚡ Launching installation process for package manager: {entry.name} ({' '.join(cmd)})")
        self.nav_list.setCurrentRow(PAGE_CONSOLE)

        worker = ExecutionWorker(cmd)
        worker.log_signal.connect(self.log)
        worker.finished_signal.connect(lambda success: self.handle_manager_install_finished(success, entry.name))
        worker.finished.connect(self._on_worker_finished)
        self.active_workers.append(worker)
        worker.start()

    def handle_manager_install_finished(self, success: bool, name: str):
        self.installing_managers.discard(name)
        if success:
            self.log(f"✅ Successfully installed package manager: {name}")
            # Rescan to update registry cache / available list
            self.scan_all()
            self.populate_managers_list()
        else:
            self.log(f"❌ Failed to install package manager: {name}")

    def console_clear(self):
        self.console.clear()

    def _forget_sudo_password(self, btn: QPushButton) -> None:
        """Remove the stored sudo password from the keyring."""
        from app.core import sudo_secret as _ss
        removed = _ss.forget()
        btn.setEnabled(False)
        lbl = self.findChild(QLabel, "sudo-pw-status")
        if lbl is not None:
            lbl.setText("No saved password (keyring unavailable or none stored)." if removed
                        else "Could not remove stored password.")
        self.log("🔑 Saved sudo password removed from keyring." if removed
                 else "⚠️ Could not remove saved sudo password.")

    def log(self, text: str):
        # Feed the terminal overlay if it's visible
        overlay = getattr(self, "terminal_overlay", None)
        if overlay is not None and overlay.isVisible():
            self._append_terminal(text)
        # Color mapping for terminal log prefixes
        color_map = {
            "✅": "#a6e3a1",  # green
            "❌": "#f38ba8",  # red
            "🔍": "#89dceb",  # cyan
            "📦": "#fab387",  # orange
            "⚡": "#cba6f7"   # purple
        }
        
        prefix = text[0] if text else ""
        color = themes.themed(color_map.get(prefix, "#cdd6f4"))  # default text color
        
        # Escape HTML characters to prevent breaking layout
        import html
        escaped_msg = html.escape(text)
        
        # Append formatted HTML string
        self.console.append(f'<span style="color: {color}; font-family: monospace;">{escaped_msg}</span>')
        self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())

    @Slot()
    def _on_worker_finished(self):
        worker = self.sender()
        if worker in self.active_workers:
            self.active_workers.remove(worker)
        if worker:
            worker.deleteLater()

    def scan_all(self):
        if self.scan_in_progress:
            self.log("⚠️ A scan is already in progress.")
            return

        self.scan_in_progress = True
        self.scan_generation += 1
        generation = self.scan_generation
        self.btn_scan.setEnabled(False)
        self.updates_list.clear()
        self.status_list.clear()
        self.managers.clear()
        self.updates_cache.clear()
        self.scan_errors.clear()
        self.selected_updates.clear()
        self.console.clear()
        system = describe_system()
        self.log(f"🖥️ Detected system: {system['arch']} / {system['distro_family']}")
        self.update_updates_badge()

        self.lbl_summary.setText("Checking for updates...")
        self.log("🔄 Starting full scan of repositories...")

        from app.core.settings_store import get_settings
        disabled = set(get_settings().disabled_managers())
        available = [m for m in discover_managers() if m.name not in disabled]
        if disabled:
            self.log(f"⏸ Not scanning (disabled in Settings): {', '.join(sorted(disabled))}")
        if not available:
            self.lbl_summary.setText("System is up to date.")
            self.log("⚠️ No active package managers found.")
            self.scan_in_progress = False
            self.btn_scan.setEnabled(True)
            self.refresh_sidebar_status()
            return

        self.manager_scan_state.clear()
        self.unsupported_reasons.clear()
        for mgr in available:
            name = mgr.name
            self.managers[name] = mgr
            self.selected_updates[name] = set()
            self.manager_scan_state[name] = "scanning"
            
            item = QListWidgetItem(f"🔍 {name} - Connecting...")
            self.status_list.addItem(item)

        worker = ScanWorker(available)
        worker.log_signal.connect(self.log)
        worker.updates_signal.connect(
            lambda manager_name, updates, g=generation: self.handle_scan_results(manager_name, updates, g)
        )
        worker.error_signal.connect(
            lambda manager_name, error, g=generation: self.handle_scan_error(manager_name, error, g)
        )
        worker.unsupported_signal.connect(
            lambda manager_name, why, g=generation: self.handle_scan_unsupported(manager_name, why, g)
        )
        worker.finished_all.connect(self.handle_scan_finished)
        worker.finished.connect(self._on_worker_finished)
        self.active_workers.append(worker)
        worker.start()

    @Slot(str, list)
    def handle_scan_results(
        self, manager_name: str, updates: list[dict[str, Any]], generation: int | None = None
    ):
        if generation is not None and generation != self.scan_generation:
            return

        from app.core.settings_store import get_settings
        settings = get_settings()
        skipped = [u.get("name", "") for u in updates if settings.is_skipped(manager_name, u)]
        if skipped:
            self.log(f"⏭ {manager_name}: hiding skipped version(s) of {', '.join(skipped)}")
            updates = [u for u in updates if not settings.is_skipped(manager_name, u)]

        self.scan_errors.pop(manager_name, None)
        self.manager_scan_state[manager_name] = "done"
        self.manager_checked_at[manager_name] = time.time()
        self.updates_cache[manager_name] = updates
        self.selected_updates.setdefault(manager_name, set())
        from app.core.ignore_store import IgnoreStore
        store = IgnoreStore()
        for pkg in updates:
            pkg_name = pkg.get("name", "")
            if not store.is_ignored(manager_name, pkg_name) and not pkg.get("blocked"):
                self.selected_updates[manager_name].add(pkg_name)
        self.update_updates_badge()

        for i in range(self.status_list.count()):
            item = self.status_list.item(i)
            if manager_name in item.text():
                category = self.managers[manager_name].category
                if updates:
                    item.setText(f"🔴 {manager_name} ({category}) - {len(updates)} updates")
                else:
                    item.setText(f"🟢 {manager_name} ({category}) - Up to date")

        self.rebuild_updates_list()

    def handle_scan_error(
        self, manager_name: str, error: str, generation: int | None = None
    ) -> None:
        """Record a failed scan without presenting it as an up-to-date manager."""
        if generation is not None and generation != self.scan_generation:
            return

        self.scan_errors[manager_name] = error
        self.manager_scan_state[manager_name] = "failed"
        self.updates_cache[manager_name] = []
        self.selected_updates.setdefault(manager_name, set()).clear()
        for i in range(self.status_list.count()):
            item = self.status_list.item(i)
            if manager_name in item.text():
                mgr = self.managers.get(manager_name)
                category = mgr.category if mgr else "Unknown"
                item.setText(f"⚠️ {manager_name} ({category}) - Scan failed")
                break
        self.update_updates_badge()
        self.rebuild_updates_list()

    def handle_scan_unsupported(self, manager_name: str, why: str, generation: int | None = None) -> None:
        """A manager with no "what's outdated" query: say so, never count it as up to date."""
        if generation is not None and generation != self.scan_generation:
            return
        self.manager_scan_state[manager_name] = "unsupported"
        self.unsupported_reasons[manager_name] = why
        self.updates_cache.pop(manager_name, None)
        for i in range(self.status_list.count()):
            item = self.status_list.item(i)
            if manager_name in item.text():
                item.setText(f"⚪ {manager_name} - can't check for updates")
                item.setToolTip(why)
                break
        self.rebuild_updates_list()

    def handle_scan_finished(self) -> None:
        self.scan_in_progress = False
        self.last_scan_at = time.time()
        self._settle_scan_states()
        self.refresh_sidebar_status()
        if self.active_operation is None:
            self.btn_scan.setEnabled(True)
        if self.pending_verification is not None:
            results, self.pending_verification = self.pending_verification, None
            self.report_upgrade_results(results)
        self.update_tray_status()

    def show_update_context_menu(self, pos) -> None:
        """Right-click on an update row opens the same menu as its "⋯" button."""
        item = self.updates_list.itemAt(pos)
        row = self.updates_list.itemWidget(item) if item else None
        if isinstance(row, UpdateItemWidget):  # not a group header or the footer
            self.show_update_menu(row, self.updates_list.viewport().mapToGlobal(pos))

    def show_update_menu(self, row: "UpdateItemWidget", global_pos=None) -> None:
        """Per-package menu: release notes, skip this version, ignore, and (DNF) vendor change."""
        if global_pos is None:
            global_pos = row.btn_menu.mapToGlobal(row.btn_menu.rect().bottomLeft())
        from app.core.ignore_store import IgnoreStore
        from app.core.settings_store import get_settings
        store, settings = IgnoreStore(), get_settings()
        mgr, pkg = row.manager_name, row.pkg_name
        menu = QMenu(self)
        driver = self.managers.get(mgr)
        url = driver.changelog_url(pkg) if driver else None
        act_notes = menu.addAction("Release notes / changelog") if url else None
        new_version = row.pkg.get("new", "")
        act_skip = menu.addAction(f"Skip version {new_version}") if new_version else None
        ignored = store.is_ignored(mgr, pkg)
        act_ignore = menu.addAction("Stop ignoring" if ignored else "Ignore this package")
        act_vendor = None
        if mgr == "DNF":
            vendor_ok = settings.get("dnf.allow_vendor_change", [])
            allowed = pkg in vendor_ok
            act_vendor = menu.addAction("Disallow vendor change" if allowed else "Allow vendor change")
        menu.addSeparator()
        act_remove = menu.addAction(f"Remove {pkg}…")
        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        if chosen is act_notes:
            QDesktopServices.openUrl(QUrl(url))
        elif chosen is act_skip:
            settings.skip_version(mgr, pkg, new_version)
            self.updates_cache[mgr] = [u for u in self.updates_cache.get(mgr, []) if u.get("name") != pkg]
            self.selected_updates.get(mgr, set()).discard(pkg)
            self.update_updates_badge()
            self.rebuild_updates_list()
        elif chosen is act_ignore:
            if ignored:
                store.remove(mgr, pkg)
            else:
                store.add(mgr, pkg)
                self.selected_updates.get(mgr, set()).discard(pkg)
            self.rebuild_updates_list()
        elif chosen is act_vendor:
            settings.set("dnf.allow_vendor_change",
                         [p for p in vendor_ok if p != pkg] if allowed else vendor_ok + [pkg])
            self.scan_all()  # the blocked flag is computed during the DNF scan
        elif chosen is act_remove:
            self.remove_package(mgr, pkg)

    def rebuild_updates_list(self):
        from app.core.ignore_store import IgnoreStore
        from app.core.settings_store import get_settings
        ignore_store = IgnoreStore()
        vendor_ok = set(get_settings().get("dnf.allow_vendor_change", []))
        self.updates_list.clear()
        total_updates = 0
        search_filter = self.search_bar.text().lower()

        up_to_date, unsupported = [], []
        for manager_name in self._update_group_order():
            updates = self.updates_cache.get(manager_name, [])
            self.selected_updates.setdefault(manager_name, set())
            state = self.manager_scan_state.get(
                manager_name, "failed" if manager_name in self.scan_errors else "done")
            if state == "unsupported":
                unsupported.append(manager_name)
                continue
            matches = [p for p in updates
                       if not search_filter or search_filter in p.get("name", "").lower()]
            if not matches and state == "done":
                if not updates:
                    up_to_date.append(manager_name)
                continue
            self._add_group_header(manager_name, updates, state)
            for pkg in matches:
                pkg_name = pkg.get("name", "")
                total_updates += 1
                row_item = QListWidgetItem(self.updates_list)

                notes = []
                if ignore_store.is_ignored(manager_name, pkg_name):
                    notes.append("🚫 Ignored — not auto-selected")
                if pkg.get("blocked"):
                    notes.append(f"⚠ dnf will skip this ({pkg['blocked']}) — use ⋯ to allow")
                elif manager_name == "DNF" and pkg_name in vendor_ok:
                    notes.append("Vendor change allowed")
                row_widget = UpdateItemWidget(pkg, manager_name, "\n".join(notes))
                row_item.setSizeHint(QSize(0, 60 + 20 * len(notes) + (24 if self.touch_mode else 0)))
                row_widget.checkbox.setChecked(pkg_name in self.selected_updates[manager_name])
                row_widget.checked_changed.connect(self.on_item_selection_changed)
                row_widget.menu_requested.connect(self.show_update_menu)

                self.updates_list.setItemWidget(row_item, row_widget)

        footers = []
        if up_to_date and total_updates:
            footers.append(("Up to date: " + ", ".join(sorted(up_to_date, key=str.lower)), ""))
        if unsupported:
            names = sorted(unsupported, key=str.lower)
            footers.append(("Can't check for updates: " + ", ".join(names),
                            "\n".join(f"{n}: {self.unsupported_reasons.get(n, '')}" for n in names)))
        for text, tip in footers:
            footer = QListWidgetItem(self.updates_list)
            footer.setFlags(Qt.ItemFlag.ItemIsEnabled)
            label = QLabel(text)
            label.setObjectName("group-footer")
            label.setWordWrap(True)
            label.setToolTip(tip)
            footer.setSizeHint(QSize(0, 36))
            self.updates_list.setItemWidget(footer, label)

        if total_updates == 0 and self.scan_errors:
            self.lbl_summary.setText(
                f"Scan failed for {len(self.scan_errors)} manager(s); see the console for details."
            )
        elif total_updates == 0:
            self.lbl_summary.setText("System is up to date.")
        else:
            suffix = f"; {len(self.scan_errors)} scan(s) failed" if self.scan_errors else ""
            self.lbl_summary.setText(f"{total_updates} update(s) available{suffix}")
        self.refresh_update_controls()

    def _update_group_order(self) -> list[str]:
        """Managers in scan order, then any with cached results that weren't in this scan."""
        names = list(self.managers)
        return names + [n for n in self.updates_cache if n not in self.managers] + [
            n for n in self.scan_errors if n not in self.managers and n not in self.updates_cache]

    def _needs_admin(self, manager_name: str) -> bool:
        """True when this manager's upgrades go through pkexec/sudo (a password prompt)."""
        mgr = self.managers.get(manager_name)
        if mgr is None:
            return False
        if getattr(mgr, "asks_for_password", False):
            return True
        try:
            cmd = mgr.get_upgrade_command([manager_name.lower()])
        except Exception:
            return False
        return bool(cmd) and cmd[0] in ("pkexec", "sudo")

    def _add_group_header(self, manager_name: str, updates: list[dict[str, Any]], state: str) -> None:
        names = {u.get("name", "") for u in updates}
        header = ManagerGroupHeader(
            manager_name, pending=len(updates),
            selected=len(self.selected_updates.get(manager_name, set()) & names), state=state,
            error=self.scan_errors.get(manager_name, ""), needs_admin=self._needs_admin(manager_name),
            checked_at=self.manager_checked_at.get(manager_name))
        header.toggle_requested.connect(self.toggle_manager_selection)
        header.retry_requested.connect(self.rescan_manager)
        item = QListWidgetItem(self.updates_list)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)  # a heading, not a selectable update
        item.setSizeHint(QSize(0, 48 + (12 if self.touch_mode else 0)))
        self.updates_list.setItemWidget(item, header)

    def toggle_manager_selection(self, manager_name: str) -> None:
        """Group checkbox: select every update of this manager, or none if all already are."""
        names = {u.get("name", "") for u in self.updates_cache.get(manager_name, [])}
        selected = self.selected_updates.setdefault(manager_name, set())
        if names and names <= selected:
            selected.clear()
        else:
            selected |= names
        self.rebuild_updates_list()

    def rescan_manager(self, manager_name: str) -> None:
        """Scan one manager again (the group header's Retry), leaving the others' results alone."""
        mgr = self.managers.get(manager_name)
        if mgr is None or self.scan_in_progress or self.manager_scan_state.get(manager_name) == "scanning":
            return
        self.manager_scan_state[manager_name] = "scanning"
        self.scan_errors.pop(manager_name, None)
        self.log(f"🔁 Retrying {manager_name} scan...")
        self.rebuild_updates_list()
        generation = self.scan_generation  # a full rescan meanwhile makes this result stale
        worker = ScanWorker([mgr])
        worker.log_signal.connect(self.log)
        worker.updates_signal.connect(
            lambda name, updates, g=generation: self.handle_scan_results(name, updates, g))
        worker.error_signal.connect(
            lambda name, error, g=generation: self.handle_scan_error(name, error, g))
        worker.unsupported_signal.connect(
            lambda name, why, g=generation: self.handle_scan_unsupported(name, why, g))
        worker.finished_all.connect(self._finish_rescan)
        worker.finished.connect(self._on_worker_finished)
        self.active_workers.append(worker)
        worker.start()

    def _finish_rescan(self) -> None:
        self._settle_scan_states()
        self.refresh_sidebar_status()
        self.rebuild_updates_list()

    def _settle_scan_states(self) -> None:
        # A manager that can't report updates emits neither results nor an error.
        for name, state in self.manager_scan_state.items():
            if state == "scanning":
                self.manager_scan_state[name] = "done"

    def _selection_counts(self) -> tuple[int, int, int, list[str], dict[str, set[str]]]:
        """(pending, selected, selected needing admin, admin managers, selected per manager)."""
        pending = 0
        selected: dict[str, set[str]] = {}
        for manager, updates in self.updates_cache.items():
            names = {u.get("name", "") for u in updates}
            pending += len(names)
            selected[manager] = self.selected_updates.get(manager, set()) & names
        admin_managers = sorted(m for m, picks in selected.items() if picks and self._needs_admin(m))
        n_selected = sum(len(p) for p in selected.values())
        n_admin = sum(len(selected[m]) for m in admin_managers)
        return pending, n_selected, n_admin, admin_managers, selected

    def refresh_update_controls(self) -> None:
        """Sync the select-all box, the primary Update button and its menu, and the bottom bar."""
        pending, n_selected, n_admin, admin_managers, _ = self._selection_counts()
        n_user = n_selected - n_admin
        box = self.chk_select_all
        box.setCheckState(Qt.CheckState.Unchecked if n_selected == 0 else
                          Qt.CheckState.Checked if n_selected >= pending else
                          Qt.CheckState.PartiallyChecked)
        box.setText(f"{n_selected} of {pending}" if pending else "")
        box.setEnabled(pending > 0)

        button = self.btn_update_selected
        button.setText(f"Update {n_selected}" if n_selected else
                       f"Update all ({len(self._all_update_targets_flat())})" if pending else "Update")
        button.setEnabled(pending > 0)
        self.act_update_selected.setText(f"Update selected ({n_selected})")
        self.act_update_selected.setEnabled(n_selected > 0)
        self.act_update_all.setText(f"Update all ({len(self._all_update_targets_flat())})")
        self.act_update_user.setText(f"Only user-level, no password ({n_user})")
        self.act_update_user.setEnabled(n_user > 0)

        self.selection_bar.update_state(n_selected, n_admin, admin_managers)
        self.selection_bar.setVisible(n_selected > 0)

    def _all_update_targets(self) -> dict[str, list[str]]:
        """Every pending update except ignored ones and those dnf would skip anyway."""
        from app.core.ignore_store import IgnoreStore
        store = IgnoreStore()
        return {m: sorted(u.get("name", "") for u in ups
                          if not u.get("blocked") and not store.is_ignored(m, u.get("name", "")))
                for m, ups in self.updates_cache.items()}

    def _all_update_targets_flat(self) -> list[str]:
        return [p for pkgs in self._all_update_targets().values() for p in pkgs]

    def run_primary_update(self) -> None:
        """The button face: update the selection, or everything when nothing is ticked."""
        if self._selection_counts()[1]:
            self.start_batch_upgrade()
        else:
            self.update_all()

    def update_all(self) -> None:
        self.start_batch_upgrade(targets=self._all_update_targets())

    def update_user_level(self) -> None:
        """Upgrade the ticked packages of managers that don't need pkexec/sudo; no password."""
        selected = self._selection_counts()[4]
        self.start_batch_upgrade(targets={
            m: sorted(picks) for m, picks in selected.items() if picks and not self._needs_admin(m)})

    def _upgrade_after_review(self, manager: str, plan: dict[str, list[str]],
                              reviewed: frozenset[str], scripts: dict) -> None:
        self._reviewing_scripts = False
        others = any(pkgs for name, pkgs in plan.items() if name != manager)
        n = len(plan.get(manager, []))
        dialog = BuildScriptDialog(manager, scripts, f"Upgrade {n}", allow_skip=others, parent=self)
        result = dialog.exec()
        if result == QDialog.DialogCode.Accepted:
            self.start_batch_upgrade(targets=plan, reviewed=reviewed | {manager})
        elif result == BuildScriptDialog.SKIP:
            self.start_batch_upgrade(targets={k: v for k, v in plan.items() if k != manager},
                                     reviewed=reviewed)

    def toggle_all_selection(self) -> None:
        """Header checkbox: select everything, or nothing when everything already is."""
        pending, n_selected = self._selection_counts()[:2]
        if pending and n_selected >= pending:
            self.deselect_all_updates()
        else:
            self.select_all_updates()

    def _sync_group_header(self, manager_name: str) -> None:
        names = {u.get("name", "") for u in self.updates_cache.get(manager_name, [])}
        picked = len(self.selected_updates.get(manager_name, set()) & names)
        for i in range(self.updates_list.count()):
            row = self.updates_list.itemWidget(self.updates_list.item(i))
            if isinstance(row, ManagerGroupHeader) and row.manager == manager_name:
                row.checkbox.setCheckState(
                    Qt.CheckState.Unchecked if picked == 0 else
                    Qt.CheckState.Checked if picked >= len(names) else Qt.CheckState.PartiallyChecked)
                return

    def select_all_updates(self):
        for manager_name, updates in self.updates_cache.items():
            self.selected_updates.setdefault(manager_name, set())
            for pkg in updates:
                self.selected_updates[manager_name].add(pkg.get("name", ""))
        self.rebuild_updates_list()

    def deselect_all_updates(self):
        for manager_name in self.selected_updates:
            self.selected_updates[manager_name].clear()
        self.rebuild_updates_list()

    def on_item_selection_changed(self, checked: bool, pkg_name: str, manager_name: str):
        if checked:
            self.selected_updates[manager_name].add(pkg_name)
        else:
            self.selected_updates[manager_name].discard(pkg_name)
            
        self.refresh_update_controls()
        # The group header's partial/all/none box reflects row ticks; rebuilding would reset
        # the scroll position, so only the header for this manager needs to follow.
        self._sync_group_header(manager_name)

    def filter_updates(self, text: str):
        self.rebuild_updates_list()

    def _confirm_commands(self, title: str, commands: list[list[str]]) -> bool:
        """Show the exact commands about to run, unless turned off in Settings. True = go ahead."""
        from app.core.settings_store import get_settings
        if not get_settings().get("ui.confirm_commands", True):
            return True
        box = QMessageBox(
            QMessageBox.Icon.Question, title, "PolyGet will run:",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel, self,
        )
        box.setInformativeText("\n\n".join(shlex.join(c) for c in commands))
        box.button(QMessageBox.StandardButton.Ok).setText("Run")
        return box.exec() == QMessageBox.StandardButton.Ok

    def start_batch_upgrade(self, *args, retry: dict[str, list[str]] | None = None,
                            targets: dict[str, list[str]] | None = None,
                            reviewed: frozenset[str] = frozenset()):
        """Upgrade the selected packages, or exactly `retry`/`targets` ({manager: packages}).

        `reviewed` names managers whose build scripts the user has already read for this run.
        """
        if retry is None:
            retry = targets
        if self.active_operation is not None:
            self.log(f"⚠️ Cannot start an upgrade while {self.active_operation} is active.")
            return

        self.upgrade_queue.clear()
        self.upgrade_failures.clear()
        self.upgrade_results = {}
        self.upgrade_unbuildable = set()
        targets = retry if retry is not None else {
            name: sorted(self.selected_updates.get(name, ())) for name in self.managers
        }
        for name, packages in targets.items():
            if packages and name in self.managers:
                self.upgrade_queue.append(UpgradeTask(self.managers[name], list(packages)))

        if not self.upgrade_queue:
            return
        commands: list[list[str]] = []
        buildable: list[UpgradeTask] = []
        unbuildable: list[str] = []
        for task in self.upgrade_queue:
            mgr, pkgs = task.manager, task.packages
            try:
                commands.append(mgr.get_upgrade_command(pkgs))
                buildable.append(UpgradeTask(mgr, pkgs))
            except (NotImplementedError, DriverError) as e:
                self._record_unbuildable(mgr.name, pkgs, e)
                unbuildable.append(mgr.name)
        self.upgrade_queue[:] = buildable
        if not self.upgrade_queue:
            # Nothing is left to run, so no end-of-run dialog will follow: say it here, not only in the console.
            QMessageBox.warning(
                self, "Cannot Upgrade",
                "PolyGet could not build an upgrade command for: " + ", ".join(unbuildable)
                + ".\n\nCheck the Process Console for the reason.",
            )
            return
        needs_review = next((t for t in self.upgrade_queue
                             if has_build_scripts(t.manager) and t.manager.name not in reviewed), None)
        if needs_review is not None:
            plan = {t.manager.name: list(t.packages) for t in self.upgrade_queue}
            self.upgrade_queue.clear()
            if self._reviewing_scripts:
                return
            self._reviewing_scripts = True
            self.log(f"📜 Fetching {needs_review.manager.name} build scripts to review...")
            worker = BuildScriptWorker(needs_review.manager, list(needs_review.packages))
            worker.result_signal.connect(
                lambda scripts, m=needs_review.manager.name, pl=plan, rv=reviewed:
                self._upgrade_after_review(m, pl, rv, scripts))
            worker.finished.connect(self._on_worker_finished)
            self.active_workers.append(worker)
            worker.start()
            return
        if not self._confirm_commands("Confirm Upgrade", commands):
            self.upgrade_queue.clear()
            return

        # Split into elevated (pkexec/sudo) and non-elevated (can run in parallel).
        # Elevated managers need sequential execution for interactive sudo auth.
        self._elevated_queue = []
        self._parallel_queue = []
        for task in self.upgrade_queue:
            mgr, pkgs = task.manager, task.packages
            cmd = mgr.get_upgrade_command(pkgs)
            if cmd and cmd[0] in ("pkexec", "sudo"):
                self._elevated_queue.append(UpgradeTask(mgr, pkgs))
            else:
                self._parallel_queue.append(UpgradeTask(mgr, pkgs))

        self.active_operation = "batch upgrade"
        self.refresh_tray_icon()
        self._show_terminal("⚡ Upgrade in progress")
        self.btn_update_selected.setEnabled(False)
        self.selection_bar.hide()
        self.btn_scan.setEnabled(False)
        self.btn_refresh_repos.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)

        self.nav_list.setCurrentRow(PAGE_CONSOLE)
        self.run_next_upgrade_queue()

    def _record_unbuildable(self, name: str, packages: list[str], error: Exception) -> None:
        """A manager whose upgrade command cannot be built still failed: log it and record it as a failed
        result, so the end-of-run dialog (built from upgrade_results) and Retry include it."""
        self.log(f"❌ {name}: cannot build an upgrade command: {describe_error(error)}")
        self.upgrade_failures.append(name)
        self.upgrade_results[name] = (list(packages), False)
        self.upgrade_unbuildable.add(name)

    def _start_upgrade_worker(self, manager, packages):
        """Start a single upgrade worker and track it."""
        try:
            cmd = manager.get_upgrade_command(packages)
        except (NotImplementedError, DriverError) as e:
            self._record_unbuildable(manager.name, packages, e)
            self._running_workers -= 1
            if self._running_workers <= 0 and not self._elevated_queue:
                self._finish_upgrade_queue()
            return

        worker = ExecutionWorker(cmd)
        worker.log_signal.connect(self.log)
        worker.finished_signal.connect(
            lambda success, mn=manager.name, pkgs=packages: self._handle_upgrade_worker_finished(success, mn, pkgs)
        )
        worker.finished.connect(self._on_worker_finished)
        self.active_workers.append(worker)
        worker.start()

    def _handle_upgrade_worker_finished(self, success: bool, manager_name: str, packages: list[str]):
        self.upgrade_results[manager_name] = (packages, success)
        if success:
            self.log(f"✅ {manager_name} upgrade command finished")
        else:
            self.log(f"❌ Failed to upgrade {manager_name}")
            self.upgrade_failures.append(manager_name)
        self._running_workers -= 1
        # Start next elevated manager if any remain
        if self._elevated_queue:
            _task = self._elevated_queue.pop(0)
            mgr, pkgs = _task.manager, _task.packages
            self._running_workers += 1
            self._start_upgrade_worker(mgr, pkgs)
        # If all workers done, finish
        if self._running_workers <= 0:
            self._finish_upgrade_queue()

    def _finish_upgrade_queue(self):
        """All upgrade workers have completed — rescan and verify."""
        if self.active_operation is None:
            return  # already finished
        self.progress.setVisible(False)
        self.terminal_overlay.hide()
        self.btn_refresh_repos.setEnabled(True)
        self.active_operation = None
        # Several tools exit 0 having changed nothing (dnf skipping a vendor change, npm
        # pinned by a range), so the rescan — not the exit code — decides what upgraded.
        self.log("🔎 Re-scanning to confirm what actually upgraded...")
        self.pending_verification = dict(self.upgrade_results)
        self.nav_list.setCurrentRow(PAGE_UPDATES)
        self.scan_all()

    def run_next_upgrade_queue(self):
        # Start all non-elevated (parallel) workers at once
        self._running_workers = len(self._parallel_queue) + (1 if self._elevated_queue else 0)
        for task in self._parallel_queue:
            self._start_upgrade_worker(task.manager, task.packages)
        self._parallel_queue = []

        # Start first elevated worker (rest queued in _elevated_queue)
        if self._elevated_queue:
            _task = self._elevated_queue.pop(0)
            mgr, pkgs = _task.manager, _task.packages
            self._start_upgrade_worker(mgr, pkgs)

        # If nothing was started, finish
        if self._running_workers <= 0:
            self._finish_upgrade_queue()

    def report_upgrade_results(self, results: dict[str, tuple[list[str], bool]]) -> None:
        """Compare an upgrade run against the rescan that followed it, log it to history, and
        tell the user what really happened, with Retry limited to what didn't work."""
        from app.core.history_store import record_upgrade
        ok, failed, unbuildable, unverified = [], [], [], []
        not_upgraded: dict[str, list[str]] = {}
        for name, (packages, success) in results.items():
            still = None
            if success and name in self.scan_errors:
                unverified.append(name)
            elif success:
                outdated = {u.get("name") for u in self.updates_cache.get(name, [])}
                still = sorted(outdated & set(packages))
            record_upgrade(name, packages, success, not_upgraded=still)
            if not success and name in self.upgrade_unbuildable:
                unbuildable.append(name)
            elif not success:
                failed.append(name)
            elif still:
                not_upgraded[name] = still
            else:
                ok.append(name)

        lines = []
        if ok:
            lines.append("✅ Upgraded: " + ", ".join(ok))
        if failed:
            lines.append("❌ Command failed: " + ", ".join(failed))
        if unbuildable:
            lines.append("🚫 No upgrade command could be built (Retry would fail the same way): " + ", ".join(unbuildable))
        if not_upgraded:
            lines.append("⚠ Finished without an error, but still outdated:\n" + "\n".join(
                f"    {name}: {', '.join(pkgs)}" for name, pkgs in not_upgraded.items()
            ) + "\nThe ⋯ button on those rows shows why (e.g. a dnf vendor change) and can skip them.")
        if unverified:
            lines.append("❔ Couldn't re-check (scan failed): " + ", ".join(unverified))
        if not failed and not unbuildable and not not_upgraded:
            QMessageBox.information(self, "Upgrade Complete", "\n\n".join(lines))
            return

        retry = {name: results[name][0] for name in failed}
        retry.update(not_upgraded)
        buttons = QMessageBox.StandardButton.Close
        if retry:
            buttons |= QMessageBox.StandardButton.Retry
        box = QMessageBox(
            QMessageBox.Icon.Warning, "Upgrade Finished With Problems",
            "\n\n".join(lines) + "\n\nCheck the Process Console for details.",
            buttons, self,
        )
        if box.exec() == QMessageBox.StandardButton.Retry and retry:
            self.start_batch_upgrade(retry=retry)

    # --- Store Browsing / Searching Functionality ---

    def on_category_changed(self, index: int):
        if index < 0:
            return
        category = self.store_category_list.item(index).text()
        if category == "All Categories":
            self.store_list.clear()
            self.lbl_store_results.setText("Type a query and press enter to search or select a category to browse...")
            return

        self.txt_store_search.clear()
        self.store_list.clear()
        self.lbl_store_results.setText(f"Loading '{category}' apps...")
        self.log(f"📂 Selected category: {category}")

        source_filter = self._store_source_filter()

        self.store_generation += 1
        generation = self.store_generation

        worker = CategoryWorker(category, source_filter)
        worker.log_signal.connect(self.log)
        worker.results_signal.connect(
            lambda results, g=generation: self.handle_store_results(results, g)
        )
        worker.finished.connect(self._on_worker_finished)
        self.active_workers.append(worker)
        worker.start()

    def _store_source_filter(self) -> str:
        """The Store's source dropdown lists real manager names, so pass the choice straight on."""
        text = self.combo_source.currentText()
        return "All" if text in ("", "All Sources") else text

    def perform_store_search(self):
        if self.chk_store_installed.isChecked():
            self.show_installed_in_store()
            return
        query = self.txt_store_search.text().strip()
        if not query:
            return

        # Reset category selection to All Categories when performing a manual search
        self.store_category_list.blockSignals(True)
        self.store_category_list.setCurrentRow(0)
        self.store_category_list.blockSignals(False)

        self.store_list.clear()
        self.lbl_store_results.setText(f"Searching database for '{query}'...")
        self.log(f"🔎 Initiated online package search for: {query}")

        source_filter = self._store_source_filter()

        self.store_generation += 1
        generation = self.store_generation

        worker = SearchWorker(query, source_filter)
        worker.log_signal.connect(self.log)
        worker.results_signal.connect(
            lambda results, g=generation: self.handle_store_results(results, g)
        )
        worker.finished.connect(self._on_worker_finished)
        self.active_workers.append(worker)
        worker.start()

    @Slot(list)
    def handle_store_results(self, results: list, generation: int | None = None):
        if generation is not None and generation != self.store_generation:
            return

        self.store_list.clear()
        if not results:
            self.lbl_store_results.setText("No search results found.")
            return

        # Calculate breakdown counts per source
        counts = {}
        for item in results:
            src = item.get("source", "Unknown")
            counts[src] = counts.get(src, 0) + 1
        breakdown = ", ".join(f"{k}: {v}" for k, v in sorted(counts.items()))

        self.lbl_store_results.setText(f"Found {len(results)} package(s) ({breakdown}):")
        for item in results:
            row_item = QListWidgetItem(self.store_list)
            row_item.setSizeHint(QSize(0, 65))

            row_widget = StoreItemWidget(item)
            row_widget.install_requested.connect(self.install_package)
            row_widget.remove_requested.connect(self.remove_package)
            self.store_list.setItemWidget(row_item, row_widget)

        # Apply any current filter immediately
        self.filter_store_results()

    def filter_store_results(self):
        filter_text = self.combo_source.currentText()
        for i in range(self.store_list.count()):
            item = self.store_list.item(i)
            widget = self.store_list.itemWidget(item)
            if widget:
                # If filter is "All Sources" or matches source type, show it
                is_match = (filter_text == "All Sources" or widget.item.get("source") == filter_text)
                item.setHidden(not is_match)

    _STORE_INSTALLED_LIMIT = 400  # rows; thousands of row widgets make the list crawl

    def on_store_installed_toggled(self, checked: bool) -> None:
        if checked:
            self.txt_store_search.setPlaceholderText("Filter installed packages...")
            self.show_installed_in_store()
        else:
            self.txt_store_search.setPlaceholderText("Search online apps and software packages...")
            self.store_generation += 1  # drop a listing still in flight
            self.store_list.clear()
            self.lbl_store_results.setText(
                "Type a query and press enter to search or select a category to browse...")

    def show_installed_in_store(self) -> None:
        """List installed packages (for the chosen source, matching the search text) in the Store."""
        from app.core.settings_store import get_settings
        source = self._store_source_filter()
        disabled = set(get_settings().disabled_managers())
        managers = [m for m in discover_managers()
                    if m.name not in disabled and (source == "All" or m.name == source)]
        self.store_generation += 1
        generation = self.store_generation
        self.store_list.clear()
        if not managers:
            self.lbl_store_results.setText("No package managers to list.")
            return
        self.lbl_store_results.setText("Listing installed packages...")
        query = self.txt_store_search.text().strip().lower()
        worker = FetchInstalledWorker(managers)
        worker.log_signal.connect(self.log)
        worker.result_signal.connect(
            lambda results, g=generation, q=query: self._show_installed_results(results, q, g))
        worker.finished.connect(self._on_worker_finished)
        self.active_workers.append(worker)
        worker.start()

    def _show_installed_results(self, results: dict, query: str, generation: int) -> None:
        if generation != self.store_generation or not self.chk_store_installed.isChecked():
            return
        items = [
            {"name": pkg, "id": pkg, "description": f"Installed with {mgr}", "version": "",
             "source": mgr, "installed": True}
            for mgr, pkgs in sorted(results.items()) for pkg in sorted(pkgs)
            if not query or query in pkg.lower()
        ]
        shown = items[:self._STORE_INSTALLED_LIMIT]
        self.handle_store_results(shown, generation)
        if len(items) > len(shown):
            self.lbl_store_results.setText(
                f"Showing {len(shown)} of {len(items)} installed packages. Type in the search box "
                "to narrow it down.")

    def remove_package(self, manager_name: str, package: str) -> None:
        """Preview what removing `package` takes with it, confirm, then run the driver's command."""
        key = f"{manager_name}:{package}"
        if key in self.removing_packages:
            self.log(f"⚠️ Removal of {package} via {manager_name} is already in progress.")
            return
        from app.core.manager import get_all_managers
        driver = self.managers.get(manager_name) or next(
            (m for m in get_all_managers() if m.name == manager_name), None)
        if driver is None or not driver.is_available():
            QMessageBox.critical(self, "Error", f"{manager_name} isn't installed.")
            return
        try:
            cmd = driver.get_remove_command([package])
        except (NotImplementedError, DriverError) as e:
            QMessageBox.information(self, "Can't remove", describe_error(e))
            return

        self.removing_packages.add(key)
        self.log(f"🔎 Checking what removing {package} would take with it...")
        worker = RemovePreviewWorker(driver, package)
        worker.result_signal.connect(
            lambda preview, error: self._confirm_remove(driver, package, cmd, preview, error))
        worker.finished.connect(self._on_worker_finished)
        self.active_workers.append(worker)
        worker.start()

    def _confirm_remove(self, driver: PackageManager, package: str, cmd: list[str],
                        preview: list[str] | None, error: str) -> None:
        key = f"{driver.name}:{package}"
        if error:
            # The dry run refused (e.g. Pacman: "still needed by gimp") or failed; never guess.
            self.removing_packages.discard(key)
            QMessageBox.warning(self, "Can't remove", f"PolyGet won't remove {package}:\n\n{error}")
            return

        lines = [f"Remove {package} with {driver.name}?", ""]
        if preview is None:
            lines += [f"{driver.name} has no dry run, so nothing beyond the command below is "
                      "checked.", ""]
        else:
            extras = [p for p in preview if p != package]
            if extras:
                lines += [f"This also removes {len(extras)} other package(s):"]
                lines += [f"  • {p}" for p in extras[:30]]
                if len(extras) > 30:
                    lines += [f"  …and {len(extras) - 30} more"]
                lines += [""]
            else:
                lines += ["Nothing else is removed with it.", ""]
        lines += ["PolyGet will run:", shlex.join(cmd)]
        confirm = QMessageBox.question(self, "Confirm Removal", "\n".join(lines),
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                       QMessageBox.StandardButton.No)
        if confirm != QMessageBox.StandardButton.Yes:
            self.removing_packages.discard(key)
            return

        self._show_terminal(f"🗑 Removing {package} via {driver.name}")
        self.log(f"🗑 Removing {package} via {driver.name}...")
        worker = ExecutionWorker(cmd)
        worker.log_signal.connect(self.log)
        worker.finished_signal.connect(
            lambda success: self.handle_remove_finished(success, driver.name, package))
        worker.finished.connect(self._on_worker_finished)
        self.active_workers.append(worker)
        worker.start()

    def handle_remove_finished(self, success: bool, manager_name: str, package: str) -> None:
        self.removing_packages.discard(f"{manager_name}:{package}")
        self.terminal_overlay.hide()
        if not success:
            QMessageBox.critical(self, "Removal Failed",
                                 f"Failed to remove {package}. Refer to the console logs.")
            return
        # It can't be outdated any more; drop it without waiting for a rescan.
        if manager_name in self.updates_cache:
            self.updates_cache[manager_name] = [
                u for u in self.updates_cache[manager_name] if u.get("name") != package]
            self.selected_updates.get(manager_name, set()).discard(package)
            self.update_updates_badge()
            self.rebuild_updates_list()
        if self.chk_store_installed.isChecked():
            self.show_installed_in_store()
        QMessageBox.information(self, "Removed", f"{package} was removed.")

    @Slot(dict)
    def install_package(self, item: dict, reviewed: bool = False):
        pkg_id = item["id"]
        source = item["source"]
        install_key = f"{source}:{pkg_id}"

        if install_key in self.installing_packages:
            self.log(f"⚠️ Installation of {item['name']} via {source} is already in progress.")
            return

        # The driver owns the command (distro quirks, elevation, Flatpak remotes); never build
        # it here. A Store result whose manager isn't installed can't be installed from here.
        from app.core.manager import get_all_managers
        driver = next((m for m in get_all_managers() if m.name == source), None)
        if driver is None or not driver.is_available():
            QMessageBox.critical(self, "Error", f"{source} isn't installed, so PolyGet can't install "
                                 f"{item['name']} with it. Install {source} from Package Managers first.")
            return
        try:
            cmd = driver.get_install_command_for(item)
        except (NotImplementedError, DriverError) as e:
            QMessageBox.critical(self, "Error", f"{source} can't install packages from PolyGet: "
                                 f"{describe_error(e)}")
            return

        if has_build_scripts(driver) and not reviewed:
            # Show the build script first; the review dialog is the confirmation.
            self.installing_packages.add(install_key)  # a second click waits for this review
            self.log(f"📜 Fetching the {source} build script for {pkg_id}...")
            worker = BuildScriptWorker(driver, [pkg_id])
            worker.result_signal.connect(
                lambda scripts: self._install_after_review(item, driver, cmd, scripts))
            worker.finished.connect(self._on_worker_finished)
            self.active_workers.append(worker)
            worker.start()
            return

        if not reviewed:
            confirm = QMessageBox.question(
                self, "Install Confirmation",
                f"Are you sure you want to install {item['name']} via {source}?\n\n"
                f"PolyGet will run:\n{shlex.join(cmd)}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return

        self.installing_packages.add(install_key)
        self._show_terminal(f"📦 Installing {item['name']} via {source}")
        self.log(f"📦 Queueing installation of {pkg_id}...")
        self.nav_list.setCurrentRow(PAGE_CONSOLE)

        # Start execution worker
        worker = ExecutionWorker(cmd)
        worker.log_signal.connect(self.log)
        worker.finished_signal.connect(
            lambda success, k=install_key: self.handle_install_finished(success, item["name"], k)
        )
        worker.finished.connect(self._on_worker_finished)
        self.active_workers.append(worker)
        worker.start()

    def _install_after_review(self, item: dict, driver: PackageManager, cmd: list[str],
                              scripts: dict) -> None:
        self.installing_packages.discard(f"{item['source']}:{item['id']}")
        dialog = BuildScriptDialog(driver.name, scripts, "Install", parent=self)
        dialog.setToolTip(shlex.join(cmd))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.install_package(item, reviewed=True)

    def handle_install_finished(self, success: bool, app_name: str, install_key: str | None = None):
        if install_key is not None:
            self.installing_packages.discard(install_key)
        self.terminal_overlay.hide()
        if success:
            QMessageBox.information(self, "Installation Complete", f"{app_name} was installed successfully!")
        else:
            QMessageBox.critical(self, "Installation Failed", f"Failed to install {app_name}. Refer to the console logs.")
        self.nav_list.setCurrentRow(PAGE_STORE)

    def sync_repositories(self):
        """Build execution queue for syncing active repositories."""
        if self.active_operation is not None:
            self.log(f"⚠️ Cannot sync repositories while {self.active_operation} is active.")
            return

        self.sync_queue.clear()
        self.sync_failures.clear()
        
        from app.core.settings_store import get_settings
        disabled = set(get_settings().disabled_managers())
        available = [m for m in discover_managers() if m.name not in disabled]
        for mgr in available:
            cmd = mgr.get_sync_command()
            if cmd:
                self.sync_queue.append(SyncTask(mgr, cmd))
                
        if not self.sync_queue:
            QMessageBox.information(self, "Sync Complete", "No active package managers support repository syncing.")
            return
        if not self._confirm_commands("Confirm Repository Sync", [cmd for _, cmd in self.sync_queue]):
            self.sync_queue.clear()
            return

        self.active_operation = "repository sync"
        self._show_terminal("🔄 Repository sync in progress")
        self.btn_scan.setEnabled(False)
        self.btn_refresh_repos.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        
        self.nav_list.setCurrentRow(PAGE_CONSOLE)
        self.run_next_sync_queue()

    def run_next_sync_queue(self):
        """Execute next repository sync command in the queue."""
        if not self.sync_queue:
            self.progress.setVisible(False)
            self.terminal_overlay.hide()
            self.btn_scan.setEnabled(True)
            self.btn_refresh_repos.setEnabled(True)
            self.active_operation = None
            if self.sync_failures:
                failed = "\n".join(f"- {name}" for name in self.sync_failures)
                QMessageBox.warning(
                    self,
                    "Repository Sync Finished With Errors",
                    f"{len(self.sync_failures)} manager(s) failed to sync.\n\n{failed}",
                )
            else:
                QMessageBox.information(self, "Sync Complete", "All repository metadata has been refreshed.")
            self.nav_list.setCurrentRow(0)
            self.scan_all()
            return

        _task = self.sync_queue.pop(0)
        manager, cmd = _task.manager, _task.command
        self.log(f"🔄 Syncing repository metadata for {manager.name}...")
        
        worker = ExecutionWorker(cmd)
        worker.log_signal.connect(self.log)
        worker.finished_signal.connect(lambda success: self.handle_sync_worker_finished(success, manager.name))
        worker.finished.connect(self._on_worker_finished)
        self.active_workers.append(worker)
        worker.start()

    def handle_sync_worker_finished(self, success: bool, manager_name: str):
        """Handle sync completion for a manager, proceed to next."""
        if success:
            self.log(f"✅ Successfully refreshed repository for {manager_name}")
        else:
            self.log(f"❌ Failed to refresh repository for {manager_name}")
            self.sync_failures.append(manager_name)
        self.run_next_sync_queue()

    def export_local_configuration(self):
        if self.active_operation is not None:
            self.log(f"⚠️ Cannot export while {self.active_operation} is active.")
            return

        self.active_operation = "blueprint export"
        self.btn_export_blueprint.setEnabled(False)
        self.btn_load_blueprint.setEnabled(False)
        self.btn_save_blueprint.setEnabled(False)
        self.btn_sync_blueprint.setEnabled(False)
        self.btn_scan.setEnabled(False)
        self.btn_refresh_repos.setEnabled(False)
        self.blueprint_progress.setVisible(True)
        self.blueprint_progress.setRange(0, 0)
        self.blueprint_status.setText("Exporting local configuration...")
        self.log("📋 Exporting local configuration as blueprint...")

        available = discover_managers()
        if not available:
            self.blueprint_status.setText("Error: No active package managers found.")
            self.blueprint_progress.setVisible(False)
            self.btn_export_blueprint.setEnabled(True)
            self.btn_load_blueprint.setEnabled(True)
            self.btn_save_blueprint.setEnabled(True)
            self.btn_sync_blueprint.setEnabled(True)
            self.btn_scan.setEnabled(True)
            self.btn_refresh_repos.setEnabled(True)
            self.active_operation = None
            return

        worker = FetchInstalledWorker(available)
        worker.log_signal.connect(self.log)
        worker.result_signal.connect(self.handle_export_results)
        worker.error_signal.connect(
            lambda errs: self.log(
                "⚠️ Blueprint is incomplete — these managers could not be queried: "
                + ", ".join(sorted(errs))
            )
        )
        worker.finished.connect(self._on_worker_finished)
        self.active_workers.append(worker)
        worker.start()

    @Slot(dict)
    def handle_export_results(self, results: dict[str, list[str]]):
        try:
            yaml_content = BlueprintManager.generate_blueprint(results)
            self.blueprint_editor.setPlainText(yaml_content)
            self.blueprint_status.setText("Blueprint generated successfully.")
            self.log("✅ Blueprint generated and loaded into editor.")
        except Exception as e:
            self.blueprint_status.setText(f"Error generating blueprint: {str(e)}")
            self.log(f"❌ Error generating blueprint: {str(e)}")
            QMessageBox.critical(self, "Export Error", f"Failed to generate blueprint: {str(e)}")

        self.blueprint_progress.setVisible(False)
        self.btn_export_blueprint.setEnabled(True)
        self.btn_load_blueprint.setEnabled(True)
        self.btn_save_blueprint.setEnabled(True)
        self.btn_sync_blueprint.setEnabled(True)
        self.btn_scan.setEnabled(True)
        self.btn_refresh_repos.setEnabled(True)
        self.active_operation = None

    def load_blueprint_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load Blueprint File", "", "YAML Files (*.yaml *.yml);;All Files (*)"
        )
        if not file_path:
            return
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.blueprint_editor.setPlainText(content)
            self.blueprint_status.setText(f"Loaded blueprint from {os.path.basename(file_path)}")
            self.log(f"📂 Loaded blueprint file: {file_path}")
        except Exception as e:
            self.blueprint_status.setText(f"Error loading file: {str(e)}")
            self.log(f"❌ Error loading blueprint file: {str(e)}")
            QMessageBox.critical(self, "Load Error", f"Failed to load blueprint file: {str(e)}")

    def save_blueprint_file(self):
        content = self.blueprint_editor.toPlainText().strip()
        if not content:
            QMessageBox.warning(self, "Save Warning", "The blueprint editor is empty.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Blueprint File", "", "YAML Files (*.yaml *.yml);;All Files (*)"
        )
        if not file_path:
            return

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            self.blueprint_status.setText(f"Saved blueprint to {os.path.basename(file_path)}")
            self.log(f"💾 Saved blueprint file: {file_path}")
        except Exception as e:
            self.blueprint_status.setText(f"Error saving file: {str(e)}")
            self.log(f"❌ Error saving blueprint file: {str(e)}")
            QMessageBox.critical(self, "Save Error", f"Failed to save blueprint file: {str(e)}")

    def sync_system_to_blueprint(self):
        content = self.blueprint_editor.toPlainText().strip()
        if not content:
            QMessageBox.warning(self, "Sync Warning", "The blueprint editor is empty.")
            return

        blueprint_data = BlueprintManager.parse_blueprint(content)
        if not blueprint_data:
            QMessageBox.critical(
                self, "Parsing Error", 
                "Failed to parse blueprint YAML. Please ensure the YAML is valid and contains a mapping of backends to lists of packages."
            )
            return

        if self.active_operation is not None:
            self.log(f"⚠️ Cannot sync blueprint while {self.active_operation} is active.")
            return

        self.active_operation = "blueprint sync"
        self._show_terminal("📋 Blueprint sync in progress")

        self.btn_export_blueprint.setEnabled(False)
        self.btn_load_blueprint.setEnabled(False)
        self.btn_save_blueprint.setEnabled(False)
        self.btn_sync_blueprint.setEnabled(False)
        self.btn_scan.setEnabled(False)
        self.btn_refresh_repos.setEnabled(False)
        self.blueprint_progress.setVisible(True)
        self.blueprint_progress.setRange(0, 0)
        self.blueprint_status.setText("Syncing: querying installed packages...")
        self.log("🔄 Starting blueprint sync: checking local system state...")

        available = discover_managers()
        self.pending_blueprint_data = blueprint_data
        
        worker = FetchInstalledWorker(available)
        worker.log_signal.connect(self.log)
        worker.result_signal.connect(self.handle_sync_check_results)
        worker.error_signal.connect(
            lambda errs: self.log(
                "⚠️ Sync check is incomplete — these managers could not be queried: "
                + ", ".join(sorted(errs))
            )
        )
        worker.finished.connect(self._on_worker_finished)
        self.active_workers.append(worker)
        worker.start()

    @Slot(dict)
    def handle_sync_check_results(self, installed_results: dict[str, list[str]]):
        blueprint_data = getattr(self, "pending_blueprint_data", {})
        
        available = discover_managers()
        manager_map = {mgr.name.lower(): mgr for mgr in available}
        
        missing_packages = []
        
        for yaml_mgr_name, yaml_pkgs in blueprint_data.items():
            mgr = manager_map.get(yaml_mgr_name.lower())
            if not mgr:
                self.log(f"⚠️ Warning: Package manager '{yaml_mgr_name}' specified in blueprint is not available on this system.")
                continue
            
            actual_mgr_name = mgr.name
            installed_pkgs = set(installed_results.get(actual_mgr_name, []))
            
            for pkg in yaml_pkgs:
                # Split on == or @ to get base package name for comparison
                base_name = pkg
                for sep in ("==", "@"):
                    if sep in pkg:
                        base_name = pkg.split(sep)[0]
                        break
                
                if base_name not in installed_pkgs:
                    missing_packages.append((mgr, pkg))

        if not missing_packages:
            self.blueprint_status.setText("System is in sync with blueprint.")
            self.log("✅ No drift detected. System is fully in sync with the blueprint.")
            QMessageBox.information(self, "Sync Complete", "System is already fully in sync with the blueprint.")
            self.blueprint_progress.setVisible(False)
            self.btn_export_blueprint.setEnabled(True)
            self.btn_load_blueprint.setEnabled(True)
            self.btn_save_blueprint.setEnabled(True)
            self.btn_sync_blueprint.setEnabled(True)
            self.btn_scan.setEnabled(True)
            self.btn_refresh_repos.setEnabled(True)
            self.active_operation = None
            return

        drift_msg = f"Found {len(missing_packages)} package(s) missing from your system:\n\n"
        for mgr, pkg in missing_packages[:15]:
            drift_msg += f" - {pkg} ({mgr.name})\n"
        if len(missing_packages) > 15:
            drift_msg += f" ... and {len(missing_packages) - 15} more\n"
        drift_msg += "\nWould you like to install them now?"

        confirm = QMessageBox.question(
            self, "Sync Confirmation - Drift Detected",
            drift_msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if confirm != QMessageBox.StandardButton.Yes:
            self.blueprint_status.setText("Sync cancelled by user.")
            self.log("⚠️ Sync cancelled by user.")
            self.blueprint_progress.setVisible(False)
            self.btn_export_blueprint.setEnabled(True)
            self.btn_load_blueprint.setEnabled(True)
            self.btn_save_blueprint.setEnabled(True)
            self.btn_sync_blueprint.setEnabled(True)
            self.btn_scan.setEnabled(True)
            self.btn_refresh_repos.setEnabled(True)
            self.active_operation = None
            return

        self.blueprint_queue.clear()
        self.blueprint_failures.clear()
        for mgr, pkg in missing_packages:
            cmd = mgr.get_install_command(pkg)
            self.blueprint_queue.append(BlueprintInstallTask(mgr, pkg, cmd))

        self.log(f"📦 Scheduled {len(missing_packages)} packages for installation.")
        self.blueprint_status.setText("Installing missing packages...")
        self.nav_list.setCurrentRow(PAGE_CONSOLE)
        self.run_next_blueprint_sync()

    def run_next_blueprint_sync(self):
        if not self.blueprint_queue:
            self.blueprint_progress.setVisible(False)
            self.terminal_overlay.hide()
            self.blueprint_status.setText("Sync complete.")
            self.log("✅ Blueprint sync complete.")
            self.nav_list.setCurrentRow(PAGE_BLUEPRINTS)
            self.btn_export_blueprint.setEnabled(True)
            self.btn_load_blueprint.setEnabled(True)
            self.btn_save_blueprint.setEnabled(True)
            self.btn_sync_blueprint.setEnabled(True)
            self.btn_scan.setEnabled(True)
            self.btn_refresh_repos.setEnabled(True)
            self.active_operation = None
            if self.blueprint_failures:
                failed = "\n".join(f"- {pkg} ({manager})" for manager, pkg in self.blueprint_failures)
                QMessageBox.warning(
                    self,
                    "Blueprint Sync Finished With Errors",
                    f"{len(self.blueprint_failures)} package(s) failed to install.\n\n{failed}",
                )
            else:
                QMessageBox.information(self, "Sync Complete", "All missing blueprint packages have been installed.")
            return

        _task = self.blueprint_queue.pop(0)
        manager, pkg, cmd = _task.manager, _task.package, _task.command
        self.log(f"⚡ Sync-installing: {pkg} via {manager.name} ({' '.join(cmd)})")
        
        worker = ExecutionWorker(cmd)
        worker.log_signal.connect(self.log)
        worker.finished_signal.connect(lambda success: self.handle_blueprint_sync_worker_finished(success, manager, pkg))
        worker.finished.connect(self._on_worker_finished)
        self.active_workers.append(worker)
        worker.start()

    def handle_blueprint_sync_worker_finished(self, success: bool, manager, pkg: str):
        if success:
            self.log(f"✅ Successfully installed {pkg} via {manager.name}")
        else:
            self.log(f"❌ Failed to install {pkg} via {manager.name}")
            self.blueprint_failures.append((manager.name, pkg))
        self.run_next_blueprint_sync()

    # --- Touch mode / window state / tray ---

    @property
    def touch_mode(self) -> bool:
        from app.core.settings_store import get_settings
        return bool(get_settings().get("ui.touch_mode", False))

    @property
    def ui_scale(self) -> float:
        """UI scale factor: 1.0 = 100%, 1.5 = 150%, etc."""
        from app.core.settings_store import get_settings
        return float(get_settings().get("ui.scale_percent", 100)) / 100.0

    @property
    def ui_font_size(self) -> int:
        """Base font size in px. 0 = use theme default (13px)."""
        from app.core.settings_store import get_settings
        return int(get_settings().get("ui.font_size", 0))

    def _px(self, base: int) -> int:
        """Scale a pixel value by the current UI scale factor."""
        return max(1, round(base * self.ui_scale))

    def _scale_qss(self, qss: str) -> str:
        """Scale all font-size values in a QSS string by font size and UI scale.

        The theme's base font is 13px. If ui.font_size is set (non-zero), it
        replaces 13px as the base; ui.scale_percent then multiplies on top.
        """
        import re
        font_size = self.ui_font_size
        scale = self.ui_scale
        if font_size > 0:
            factor = (font_size / 13.0) * scale
        else:
            factor = scale
        if abs(factor - 1.0) < 0.001:
            return qss
        return re.sub(
            r'font-size:\s*(\d+)px',
            lambda m: f'font-size: {max(1, round(int(m.group(1)) * factor))}px',
            qss,
        )

    def apply_touch_mode(self) -> None:
        """Re-theme with finger-sized targets (44px+) when touch mode is on; safe to call live."""
        self.apply_theme()
        touch = self.touch_mode
        if touch:
            # Append to the Mocha source, not the themed output, so colours are mapped once.
            self.setStyleSheet((self.property("_polyget_qss_src") or self.styleSheet()) + _TOUCH_QSS)
            # Wider sidebar so the fatter scrollbar doesn't clip the nav labels.
            sizes = self.main_splitter.sizes()
            if sizes and sizes[0] < 300 and self.sidebar_nav_style != "rail":
                self.main_splitter.setSizes([300, max(sum(sizes) - 300, 400)])
        for i in range(self.nav_list.count()):
            item = self.nav_list.item(i)
            if touch:
                item.setSizeHint(QSize(0, 52))
            else:
                item.setSizeHint(self.nav_native_row_size if i <= PAGE_VERSION_CHECK else QSize())
        self.rebuild_updates_list()

    def restore_window_state(self) -> None:
        state = QSettings("PolyGet", "PolyGet")
        geometry = state.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        page = int(state.value("window/page", PAGE_UPDATES))
        if 0 <= page < self.nav_list.count():
            self.nav_list.setCurrentRow(page)

    def save_window_state(self) -> None:
        state = QSettings("PolyGet", "PolyGet")
        state.setValue("window/geometry", self.saveGeometry())
        state.setValue("window/page", self.nav_list.currentRow())

    def setup_tray(self) -> None:
        """Create or remove the tray icon and (re)arm the background-scan timer from Settings."""
        from app.core.settings_store import get_settings
        settings = get_settings()
        enabled = bool(settings.get("tray.enabled", False)) and QSystemTrayIcon.isSystemTrayAvailable()
        QApplication.instance().setQuitOnLastWindowClosed(not enabled)
        if not enabled:
            if self.tray is not None:
                self.tray.hide()
                self.tray = None
            self.bg_timer.stop()
            return
        if self.tray is None:
            self._tray_icon_state = None
            self.tray = QSystemTrayIcon(tray_icon("idle", theme_qt.system_is_dark()), self)
            menu = QMenu(self)
            menu.addAction("Open PolyGet", self.show_from_tray)
            menu.addAction("Check for Updates", self.background_scan)
            menu.addSeparator()
            menu.addAction("Quit", self.quit_from_tray)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(
                lambda reason: self.show_from_tray()
                if reason == QSystemTrayIcon.ActivationReason.Trigger else None
            )
            self.tray.messageClicked.connect(self.show_from_tray)
            self.tray.show()
        hours = int(settings.get("tray.scan_interval_hours", 6))
        if hours > 0:
            self.bg_timer.start(hours * 3600 * 1000)
        else:
            self.bg_timer.stop()
        self.update_tray_status()

    def _setup_keyboard_shortcuts(self) -> None:
        """Register global keyboard shortcuts for the most common actions."""
        shortcuts = [
            ("Ctrl+R", self.scan_all, "Check for Updates"),
            ("Ctrl+U", self.start_batch_upgrade, "Update Selected"),
            ("Ctrl+S", self.sync_repositories, "Sync Repositories"),
            ("Ctrl+Shift+U", self.run_version_check, "Run Version Scan"),
            ("F1", lambda: self.nav_list.setCurrentRow(PAGE_DEBUG), "Open Debug Console"),
            ("Escape", self._hide_terminal_if_visible, "Hide Terminal Overlay"),
            ("Ctrl+Q", self.close, "Quit PolyGet"),
        ]
        for key_seq, slot, _desc in shortcuts:
            sc = QShortcut(QKeySequence(key_seq), self)
            sc.activated.connect(slot)

    def _hide_terminal_if_visible(self) -> None:
        """Hide the terminal overlay if it's currently visible; otherwise do nothing."""
        overlay = getattr(self, "terminal_overlay", None)
        if overlay is not None and overlay.isVisible():
            overlay.hide()

    def show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_from_tray(self) -> None:
        self.really_quit = True
        if self.close():
            QApplication.quit()
        else:
            self.really_quit = False

    def background_scan(self) -> None:
        if self.scan_in_progress or self.active_operation is not None:
            return
        self.notify_after_scan = True
        self.scan_all()

    def update_tray_status(self) -> None:
        """Refresh the tray tooltip, and notify about updates not announced before."""
        if self.tray is None:
            return
        current = {
            (mgr, u.get("name", ""), u.get("new", ""))
            for mgr, updates in self.updates_cache.items() for u in updates
        }
        self.tray.setToolTip(f"PolyGet — {len(current)} update(s)" if current else "PolyGet — up to date")
        from app.core.settings_store import get_settings
        fresh = current - self.notified_updates
        should_notify = self.notify_after_scan or not self.isVisible()
        if fresh and should_notify and get_settings().get("tray.notify", True):
            names = ", ".join(sorted(name for _, name, _ in fresh)[:5])
            more = f" and {len(fresh) - 5} more" if len(fresh) > 5 else ""
            self.tray.showMessage(f"{len(fresh)} new update(s)", names + more,
                                  QSystemTrayIcon.MessageIcon.Information)
        self.notified_updates |= current
        self.notify_after_scan = False

    def closeEvent(self, event):
        """Prompt user on exit if active background child processes exist, then terminate them."""
        self.save_window_state()
        if self.tray is not None and not self.really_quit:
            # Closing with the tray on just hides the window; Quit is in the tray menu.
            event.ignore()
            self.hide()
            return
        coordinator = SubprocessCoordinator()
        active_pids = coordinator.active_pids
        if active_pids:
            reply = QMessageBox.question(
                self,
                "Confirm Exit",
                f"There are {len(active_pids)} active background update processes running.\n"
                "Are you sure you want to exit? Active tasks will be terminated.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.No:
                event.ignore()
                return
            coordinator.terminate_all()

        self._shutdown_workers()
        event.accept()

    def _shutdown_workers(self):
        """Stop and join background QThreads so Qt doesn't destroy them mid-run.

        These workers override run() directly rather than calling exec(), so
        QThread.quit() has nothing to do — it only stops a thread's own event
        loop. Killing the tracked subprocesses above lets ExecutionWorker
        threads unblock and exit on their own within the first wait(); anything
        else (e.g. a network-bound search) gets a forceful terminate() as a
        fallback. Both waits are bounded so shutdown can never hang, even if a
        thread doesn't respond to terminate() promptly.
        """
        for worker in list(self.active_workers):
            if not worker.wait(3000):
                worker.terminate()
                worker.wait(2000)
