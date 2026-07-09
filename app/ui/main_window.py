import sys
import os
import glob
import asyncio
import shutil
from typing import Any
from PySide6.QtCore import Qt, QThread, Signal, Slot, QSize
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QPlainTextEdit, QProgressBar, QMessageBox, QCheckBox,
    QLineEdit, QStackedWidget, QSplitter, QFrame, QComboBox, QFileDialog
)
from app.core.manager import discover_managers, PackageManager
from app.core.coordinator import SubprocessCoordinator
from app.core.blueprint import BlueprintManager


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


class UpdateWorker(QThread):
    """Worker thread to run asynchronous scanning."""
    log_signal = Signal(str)
    updates_signal = Signal(str, list)  # manager_name, list of updates

    def __init__(self, manager: PackageManager, parent: Any = None):
        super().__init__(parent)
        self.manager = manager
        self.updates: list[dict[str, Any]] = []

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.log_signal.emit(f"🔍 Scanning {self.manager.name} for updates...")
        try:
            self.updates = loop.run_until_complete(self.manager.check_updates())
            self.updates_signal.emit(self.manager.name, self.updates)
            self.log_signal.emit(f"✅ Scan complete for {self.manager.name}. Found {len(self.updates)} update(s).")
        except Exception as e:
            self.log_signal.emit(f"❌ Error scanning {self.manager.name}: {str(e)}")
            self.updates_signal.emit(self.manager.name, [])
        loop.close()


class ExecutionWorker(QThread):
    """General purpose execution worker piping command outputs to the logs."""
    log_signal = Signal(str)
    finished_signal = Signal(bool)

    def __init__(self, cmd: list[str], parent: Any = None):
        super().__init__(parent)
        self.cmd = cmd

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.log_signal.emit(f"⚡ Executing: {' '.join(self.cmd)}")
        try:
            async def run_cmd():
                run_cmd_list = list(self.cmd)
                proc = await asyncio.create_subprocess_exec(
                    *run_cmd_list,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    preexec_fn=os.setsid
                )
                coordinator = SubprocessCoordinator()
                coordinator.register(proc.pid)
                try:
                    while True:
                        line = await proc.stdout.readline()
                        if not line:
                            break
                        line_str = line.decode(errors="ignore").strip()
                        self.log_signal.emit(line_str)
                    return await proc.wait()
                finally:
                    coordinator.unregister(proc.pid)

            exit_code = loop.run_until_complete(run_cmd())
            self.finished_signal.emit(exit_code == 0)
        except Exception as e:
            self.log_signal.emit(f"❌ Execution error: {str(e)}")
            self.finished_signal.emit(False)
        loop.close()


class SearchWorker(QThread):
    """Worker thread to run asynchronous searches across DNF, Flatpak, NPM, Cargo, and Pipx."""
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

        async def search_flatpak():
            if self.source_filter in ("All", "Flatpak") and shutil.which("flatpak"):
                try:
                    proc = await asyncio.create_subprocess_exec(
                        "flatpak", "search", "-j", self.query,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    stdout, _ = await proc.communicate()
                    if stdout:
                        import json
                        data = json.loads(stdout.decode(errors="ignore"))
                        for item in data:
                            results.append({
                                "name": item.get("name", ""),
                                "id": item.get("application_id", ""),
                                "description": item.get("description", ""),
                                "version": item.get("version", ""),
                                "source": "Flatpak",
                                "remote": item.get("remotes", "flathub").split(",")[0]
                            })
                except Exception as e:
                    self.log_signal.emit(f"Flatpak search error: {str(e)}")

        async def search_dnf():
            if self.source_filter in ("All", "DNF") and shutil.which("dnf"):
                try:
                    proc = await asyncio.create_subprocess_exec(
                        "dnf", "search", self.query,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    stdout, _ = await proc.communicate()
                    import re
                    pattern = re.compile(r'^\s*([a-zA-Z0-9\-_+.]+)\.([a-zA-Z0-9_]+)\s+(.+)$')
                    for line in stdout.decode(errors="ignore").splitlines():
                        match = pattern.match(line)
                        if match:
                            pkg_name = match.group(1)
                            desc = match.group(3)
                            # Ignore debug/devel meta packages
                            if any(x in pkg_name for x in ("-debuginfo", "-debugsource", ".src")):
                                continue
                            results.append({
                                "name": pkg_name,
                                "id": pkg_name,
                                "description": desc,
                                "version": "",
                                "source": "DNF",
                                "remote": ""
                            })
                except Exception as e:
                    self.log_signal.emit(f"DNF search error: {str(e)}")

        async def search_cargo():
            if self.source_filter in ("All", "Cargo") and shutil.which("cargo"):
                try:
                    proc = await asyncio.create_subprocess_exec(
                        "cargo", "search", "--limit", "20", self.query,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    stdout, _ = await proc.communicate()
                    import re
                    pattern = re.compile(r'^([a-zA-Z0-9\-_+.]+)\s*=\s*"([^"]+)"\s*#\s*(.+)$')
                    for line in stdout.decode(errors="ignore").splitlines():
                        match = pattern.match(line.strip())
                        if match:
                            pkg_name = match.group(1)
                            version = match.group(2)
                            desc = match.group(3)
                            results.append({
                                "name": pkg_name,
                                "id": pkg_name,
                                "description": desc,
                                "version": version,
                                "source": "Cargo",
                                "remote": ""
                            })
                except Exception as e:
                    self.log_signal.emit(f"Cargo search error: {str(e)}")

        async def search_npm():
            if self.source_filter in ("All", "NPM") and shutil.which("npm"):
                try:
                    proc = await asyncio.create_subprocess_exec(
                        "npm", "search", "--json", self.query,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    stdout, _ = await proc.communicate()
                    if stdout:
                        import json
                        data = json.loads(stdout.decode(errors="ignore"))
                        if isinstance(data, list):
                            for item in data[:20]:
                                results.append({
                                    "name": item.get("name", ""),
                                    "id": item.get("name", ""),
                                    "description": item.get("description", ""),
                                    "version": item.get("version", ""),
                                    "source": "NPM",
                                    "remote": ""
                                })
                except Exception as e:
                    self.log_signal.emit(f"NPM search error: {str(e)}")

        async def search_pipx():
            if self.source_filter in ("All", "Pipx"):
                import json
                try:
                    proc = await asyncio.create_subprocess_exec(
                        "curl", "-s", "-H", "User-Agent: PolyGet/1.0", f"https://pypi.org/pypi/{self.query}/json",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    stdout, _ = await proc.communicate()
                    if stdout:
                        data = json.loads(stdout.decode(errors="ignore"))
                        info = data.get("info", {})
                        if info:
                            results.append({
                                "name": info.get("name", ""),
                                "id": info.get("name", ""),
                                "description": info.get("summary", ""),
                                "version": info.get("version", ""),
                                "source": "Pipx",
                                "remote": ""
                            })
                except Exception as e:
                    self.log_signal.emit(f"Pipx search error: {str(e)}")

        tasks = []
        if self.source_filter in ("All", "Flatpak"):
            tasks.append(search_flatpak())
        if self.source_filter in ("All", "DNF"):
            tasks.append(search_dnf())
        if self.source_filter in ("All", "Cargo"):
            tasks.append(search_cargo())
        if self.source_filter in ("All", "NPM"):
            tasks.append(search_npm())
        if self.source_filter in ("All", "Pipx"):
            tasks.append(search_pipx())

        if tasks:
            loop.run_until_complete(asyncio.gather(*tasks))
        loop.close()
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
                    elif "package" in comp:
                        pkg_id = comp["package"]
                        source = "DNF"

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
        self.results_signal.emit(results)


class FetchInstalledWorker(QThread):
    """Worker thread to query installed packages across all available managers."""
    log_signal = Signal(str)
    result_signal = Signal(dict)

    def __init__(self, managers: list[PackageManager], parent: Any = None):
        super().__init__(parent)
        self.managers = managers

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        self.log_signal.emit("🔍 Querying installed packages across all managers...")
        results = {}
        
        async def fetch_installed(mgr: PackageManager):
            self.log_signal.emit(f"📦 Querying installed packages from {mgr.name}...")
            try:
                pkgs = await mgr.list_installed()
                self.log_signal.emit(f"✅ Found {len(pkgs)} installed packages for {mgr.name}.")
                return mgr.name, pkgs
            except Exception as e:
                self.log_signal.emit(f"❌ Error querying {mgr.name}: {str(e)}")
                return mgr.name, []

        tasks = [fetch_installed(mgr) for mgr in self.managers]
        done = loop.run_until_complete(asyncio.gather(*tasks))
        loop.close()
        
        for name, pkgs in done:
            results[name] = pkgs
            
        self.result_signal.emit(results)


class UpdateItemWidget(QWidget):
    """Custom row widget replicating KDE Discover's update list items."""
    checked_changed = Signal(bool, str, str)

    def __init__(self, pkg: dict[str, Any], manager_name: str, parent: Any = None):
        super().__init__(parent)
        self.pkg_name = pkg.get("name", "")
        self.manager_name = manager_name
        self.setup_ui(pkg, manager_name)

    def setup_ui(self, pkg: dict[str, Any], manager_name: str):
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

        version_info = f"{pkg.get('current', '')}  ➔  {pkg.get('new', '')}"
        lbl_version = QLabel(version_info)
        lbl_version.setStyleSheet("color: #9ca3af; font-size: 12px;")
        details_layout.addWidget(lbl_version)

        layout.addLayout(details_layout)
        layout.addStretch()

        lbl_source = QLabel(manager_name)
        if manager_name == "DNF":
            badge_style = "background-color: #1e3a8a; color: #93c5fd;"
        elif manager_name == "Flatpak":
            badge_style = "background-color: #064e3b; color: #6ee7b7;"
        else:
            badge_style = "background-color: #581c87; color: #d8b4fe;"
        lbl_source.setStyleSheet(badge_style + "border-radius: 12px; padding: 4px 12px; font-weight: bold; font-size: 11px;")
        layout.addWidget(lbl_source)

    def on_checkbox_toggled(self, state: int):
        self.checked_changed.emit(state == 2, self.pkg_name, self.manager_name)


class StoreItemWidget(QWidget):
    """Custom row widget representing search results in the package store."""
    install_requested = Signal(dict)

    def __init__(self, item: dict[str, Any], parent: Any = None):
        super().__init__(parent)
        self.item = item
        self.setup_ui()

    def setup_ui(self):
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

        # Install Button
        self.btn_install = QPushButton("Install")
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
        self.btn_install.clicked.connect(lambda: self.install_requested.emit(self.item))
        layout.addWidget(self.btn_install)


class MainWindow(QMainWindow):
    """Main window supporting unified updates, package browsing, and logs."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PolyGet")
        self.resize(1050, 700)
        self.managers: dict[str, PackageManager] = {}
        self.updates_cache: dict[str, list[dict[str, Any]]] = {}
        self.selected_updates: dict[str, set[str]] = {}
        self.active_workers: list[QThread] = []
        self.upgrade_queue: list[tuple[PackageManager, list[str]]] = []
        
        self.setup_ui()
        self.apply_theme()
        self.scan_all()

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        # --- Sidebar Panel ---
        sidebar_widget = QWidget()
        sidebar_widget.setObjectName("sidebar-panel")
        sidebar_layout = QVBoxLayout(sidebar_widget)
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
        
        item_updates = QListWidgetItem("System Updates")
        item_updates.setIcon(QIcon.fromTheme("system-software-update"))
        self.nav_list.addItem(item_updates)

        item_store = QListWidgetItem("Browse Store")
        item_store.setIcon(QIcon.fromTheme("emblem-downloads"))
        self.nav_list.addItem(item_store)

        item_console = QListWidgetItem("Process Console")
        item_console.setIcon(QIcon.fromTheme("utilities-terminal"))
        self.nav_list.addItem(item_console)
        
        item_blueprints = QListWidgetItem("Blueprints")
        item_blueprints.setIcon(QIcon.fromTheme("document-properties"))
        self.nav_list.addItem(item_blueprints)
        
        self.nav_list.setCurrentRow(0)
        self.nav_list.currentRowChanged.connect(self.change_page)
        sidebar_layout.addWidget(self.nav_list)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #374151;")
        sidebar_layout.addWidget(line)

        lbl_sources = QLabel("Active Repositories")
        lbl_sources.setObjectName("sidebar-title")
        sidebar_layout.addWidget(lbl_sources)

        self.status_list = QListWidget()
        self.status_list.setObjectName("status-list")
        self.status_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
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
        self.lbl_summary = QLabel("Checking for updates...")
        self.lbl_summary.setObjectName("summary-label")
        updates_header.addWidget(self.lbl_summary)
        updates_header.addStretch()

        self.btn_update_selected = QPushButton("Update Selected")
        self.btn_update_selected.setObjectName("btn-update-all")
        self.btn_update_selected.setEnabled(False)
        self.btn_update_selected.clicked.connect(self.start_batch_upgrade)
        updates_header.addWidget(self.btn_update_selected)
        updates_layout.addLayout(updates_header)

        self.updates_list = QListWidget()
        self.updates_list.setObjectName("updates-list")
        updates_layout.addWidget(self.updates_list)

        # Progress bar
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        updates_layout.addWidget(self.progress)

        self.stacked_widget.addWidget(updates_page)

        # PAGE 2: Browse Store
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
        self.combo_source.addItems(["All Sources", "Flatpak", "DNF", "NPM", "Cargo", "Pipx"])
        self.combo_source.setStyleSheet("""
            QComboBox {
                background-color: #11111b;
                border: 1px solid #313244;
                border-radius: 6px;
                padding: 6px 12px;
                color: #cdd6f4;
            }
        """)
        store_header.addWidget(self.combo_source, stretch=1)

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

        self.console = QPlainTextEdit()
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
        self.blueprint_editor.setObjectName("console-output")
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
        splitter.addWidget(self.stacked_widget)

        splitter.setSizes([250, 750])

    def apply_theme(self):
        """Apply a premium dark-mode theme stylesheet."""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e2e;
            }
            QWidget {
                color: #cdd6f4;
                font-family: 'Outfit', 'Inter', 'Segoe UI', sans-serif;
                font-size: 13px;
            }
            QWidget#sidebar-panel {
                background-color: #181825;
                border-right: 1px solid #313244;
            }
            QLabel#sidebar-title {
                font-weight: bold;
                color: #89b4fa;
                font-size: 12px;
                text-transform: uppercase;
                margin-top: 10px;
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
            QListWidget#nav-list::item, QListWidget#status-list::item {
                padding: 10px 12px;
                border-radius: 6px;
                margin-bottom: 2px;
            }
            QListWidget#nav-list::item:selected {
                background-color: #313244;
                color: #89b4fa;
                font-weight: bold;
            }
            QListWidget#nav-list::item:hover:!selected {
                background-color: #1e1e2e;
            }
            QListWidget#updates-list {
                background-color: #181825;
                border: 1px solid #313244;
                border-radius: 8px;
            }
            QListWidget#updates-list::item {
                border-bottom: 1px solid #313244;
            }
            QListWidget#updates-list::item:last {
                border-bottom: none;
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
            QPlainTextEdit#console-output {
                background-color: #11111b;
                border: 1px solid #313244;
                border-radius: 8px;
                font-family: 'Fira Code', 'Courier New', monospace;
                color: #a6e3a1;
                font-size: 12px;
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
        """)

    def change_page(self, index: int):
        if index >= 0:
            self.stacked_widget.setCurrentIndex(index)

    def console_clear(self):
        self.console.clear()

    def log(self, text: str):
        self.console.appendPlainText(text)
        self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())

    @Slot()
    def _on_worker_finished(self):
        worker = self.sender()
        if worker in self.active_workers:
            self.active_workers.remove(worker)
        if worker:
            worker.deleteLater()

    def scan_all(self):
        self.updates_list.clear()
        self.status_list.clear()
        self.managers.clear()
        self.updates_cache.clear()
        self.selected_updates.clear()
        self.console.clear()
        
        self.lbl_summary.setText("Checking for updates...")
        self.log("🔄 Starting full scan of repositories...")

        available = discover_managers()
        if not available:
            self.lbl_summary.setText("System is up to date.")
            self.log("⚠️ No active package managers found.")
            return

        for mgr in available:
            name = mgr.name
            self.managers[name] = mgr
            self.selected_updates[name] = set()
            
            item = QListWidgetItem(f"🔍 {name} - Connecting...")
            self.status_list.addItem(item)

            worker = UpdateWorker(mgr)
            worker.log_signal.connect(self.log)
            worker.updates_signal.connect(self.handle_scan_results)
            worker.finished.connect(self._on_worker_finished)
            self.active_workers.append(worker)
            worker.start()

    @Slot(str, list)
    def handle_scan_results(self, manager_name: str, updates: list[dict[str, Any]]):
        self.updates_cache[manager_name] = updates
        for pkg in updates:
            self.selected_updates[manager_name].add(pkg.get("name", ""))

        for i in range(self.status_list.count()):
            item = self.status_list.item(i)
            if manager_name in item.text():
                category = self.managers[manager_name].category
                if updates:
                    item.setText(f"🔴 {manager_name} ({category}) - {len(updates)} updates")
                else:
                    item.setText(f"🟢 {manager_name} ({category}) - Up to date")

        self.rebuild_updates_list()

    def rebuild_updates_list(self):
        self.updates_list.clear()
        total_updates = 0
        search_filter = self.search_bar.text().lower()

        for manager_name, updates in self.updates_cache.items():
            for pkg in updates:
                pkg_name = pkg.get("name", "")
                if search_filter and search_filter not in pkg_name.lower():
                    continue

                total_updates += 1
                row_item = QListWidgetItem(self.updates_list)
                row_item.setSizeHint(QSize(0, 60))

                row_widget = UpdateItemWidget(pkg, manager_name)
                row_widget.checkbox.setChecked(pkg_name in self.selected_updates[manager_name])
                row_widget.checked_changed.connect(self.on_item_selection_changed)

                self.updates_list.setItemWidget(row_item, row_widget)

        if total_updates == 0:
            self.lbl_summary.setText("System is up to date.")
            self.btn_update_selected.setEnabled(False)
        else:
            selected_count = sum(len(s) for s in self.selected_updates.values())
            self.lbl_summary.setText(f"{total_updates} update(s) available ({selected_count} selected)")
            self.btn_update_selected.setEnabled(selected_count > 0)

        nav_item = self.nav_list.item(0)
        if total_updates > 0:
            nav_item.setText(f"System Updates ({total_updates})")
        else:
            nav_item.setText("System Updates")

    def on_item_selection_changed(self, checked: bool, pkg_name: str, manager_name: str):
        if checked:
            self.selected_updates[manager_name].add(pkg_name)
        else:
            self.selected_updates[manager_name].discard(pkg_name)
            
        selected_count = sum(len(s) for s in self.selected_updates.values())
        total_updates = sum(len(u) for u in self.updates_cache.values())
        self.lbl_summary.setText(f"{total_updates} update(s) available ({selected_count} selected)")
        self.btn_update_selected.setEnabled(selected_count > 0)

    def filter_updates(self, text: str):
        self.rebuild_updates_list()

    def start_batch_upgrade(self):
        self.upgrade_queue.clear()
        for name, manager in self.managers.items():
            selected = list(self.selected_updates[name])
            if selected:
                self.upgrade_queue.append((manager, selected))

        if not self.upgrade_queue:
            return

        self.btn_update_selected.setEnabled(False)
        self.btn_scan.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        
        self.nav_list.setCurrentRow(2)  # Switch to console
        self.run_next_upgrade_queue()

    def run_next_upgrade_queue(self):
        if not self.upgrade_queue:
            self.progress.setVisible(False)
            self.btn_scan.setEnabled(True)
            QMessageBox.information(self, "Batch Upgrade Complete", "All selected package upgrades have finished.")
            self.nav_list.setCurrentRow(0)
            self.scan_all()
            return

        manager, packages = self.upgrade_queue.pop(0)
        cmd = manager.get_upgrade_command(packages)
        
        worker = ExecutionWorker(cmd)
        worker.log_signal.connect(self.log)
        worker.finished_signal.connect(lambda success: self.handle_queue_worker_finished(success))
        worker.finished.connect(self._on_worker_finished)
        self.active_workers.append(worker)
        worker.start()

    def handle_queue_worker_finished(self, success: bool):
        self.run_next_upgrade_queue()

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

        source_filter = "All"
        sel_text = self.combo_source.currentText()
        if "Flatpak" in sel_text:
            source_filter = "Flatpak"
        elif "DNF" in sel_text:
            source_filter = "DNF"

        worker = CategoryWorker(category, source_filter)
        worker.log_signal.connect(self.log)
        worker.results_signal.connect(self.handle_store_results)
        worker.finished.connect(self._on_worker_finished)
        self.active_workers.append(worker)
        worker.start()

    def perform_store_search(self):
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

        source_filter = "All"
        sel_text = self.combo_source.currentText()
        if "Flatpak" in sel_text:
            source_filter = "Flatpak"
        elif "DNF" in sel_text:
            source_filter = "DNF"
        elif "NPM" in sel_text:
            source_filter = "NPM"
        elif "Cargo" in sel_text:
            source_filter = "Cargo"
        elif "Pipx" in sel_text:
            source_filter = "Pipx"

        worker = SearchWorker(query, source_filter)
        worker.log_signal.connect(self.log)
        worker.results_signal.connect(self.handle_store_results)
        worker.finished.connect(self._on_worker_finished)
        self.active_workers.append(worker)
        worker.start()

    @Slot(list)
    def handle_store_results(self, results: list):
        self.store_list.clear()
        if not results:
            self.lbl_store_results.setText("No search results found.")
            return

        self.lbl_store_results.setText(f"Found {len(results)} package(s):")
        for item in results:
            row_item = QListWidgetItem(self.store_list)
            row_item.setSizeHint(QSize(0, 65))

            row_widget = StoreItemWidget(item)
            row_widget.install_requested.connect(self.install_package)
            self.store_list.setItemWidget(row_item, row_widget)

    @Slot(dict)
    def install_package(self, item: dict):
        pkg_id = item["id"]
        source = item["source"]
        
        confirm = QMessageBox.question(
            self, "Install Confirmation",
            f"Are you sure you want to install {item['name']} via {source}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        # Prepare installation command based on source
        if source == "Flatpak":
            remote = item.get("remote", "flathub")
            cmd = ["flatpak", "install", "-y", remote, pkg_id]
        elif source == "DNF":
            cmd = ["pkexec", "dnf", "install", "-y", pkg_id]
        elif source == "Cargo":
            cmd = ["cargo", "install", pkg_id]
        elif source == "NPM":
            cmd = ["npm", "install", "-g", pkg_id]
        elif source == "Pipx":
            cmd = ["pipx", "install", pkg_id]
        else:
            QMessageBox.critical(self, "Error", f"No installer available for source '{source}'.")
            return

        self.log(f"📦 Queueing installation of {pkg_id}...")
        self.nav_list.setCurrentRow(2)  # Switch to console

        # Start execution worker
        worker = ExecutionWorker(cmd)
        worker.log_signal.connect(self.log)
        worker.finished_signal.connect(lambda success: self.handle_install_finished(success, item["name"]))
        worker.finished.connect(self._on_worker_finished)
        self.active_workers.append(worker)
        worker.start()

    def handle_install_finished(self, success: bool, app_name: str):
        if success:
            QMessageBox.information(self, "Installation Complete", f"{app_name} was installed successfully!")
        else:
            QMessageBox.critical(self, "Installation Failed", f"Failed to install {app_name}. Refer to the console logs.")
        self.nav_list.setCurrentRow(1)  # Return to store page

    def sync_repositories(self):
        """Build execution queue for syncing active repositories."""
        self.upgrade_queue.clear()
        
        available = discover_managers()
        for mgr in available:
            cmd = mgr.get_sync_command()
            if cmd:
                self.upgrade_queue.append((mgr, cmd))
                
        if not self.upgrade_queue:
            QMessageBox.information(self, "Sync Complete", "No active package managers support repository syncing.")
            return

        self.btn_scan.setEnabled(False)
        self.btn_refresh_repos.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        
        self.nav_list.setCurrentRow(2)  # Switch to console
        self.run_next_sync_queue()

    def run_next_sync_queue(self):
        """Execute next repository sync command in the queue."""
        if not self.upgrade_queue:
            self.progress.setVisible(False)
            self.btn_scan.setEnabled(True)
            self.btn_refresh_repos.setEnabled(True)
            QMessageBox.information(self, "Sync Complete", "All repository metadata has been refreshed.")
            self.nav_list.setCurrentRow(0)
            self.scan_all()
            return

        manager, cmd = self.upgrade_queue.pop(0)
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
        self.run_next_sync_queue()

    def export_local_configuration(self):
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
            return

        worker = FetchInstalledWorker(available)
        worker.log_signal.connect(self.log)
        worker.result_signal.connect(self.handle_export_results)
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
                if pkg not in installed_pkgs:
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
            return

        self.upgrade_queue.clear()
        for mgr, pkg in missing_packages:
            cmd = mgr.get_install_command(pkg)
            self.upgrade_queue.append((mgr, pkg, cmd))

        self.log(f"📦 Scheduled {len(missing_packages)} packages for installation.")
        self.blueprint_status.setText("Installing missing packages...")
        self.nav_list.setCurrentRow(2)  # Switch to console
        self.run_next_blueprint_sync()

    def run_next_blueprint_sync(self):
        if not self.upgrade_queue:
            self.blueprint_progress.setVisible(False)
            self.blueprint_status.setText("Sync complete.")
            self.log("✅ Blueprint sync complete.")
            QMessageBox.information(self, "Sync Complete", "All missing blueprint packages have been installed.")
            self.nav_list.setCurrentRow(3)  # Return to blueprints page
            self.btn_export_blueprint.setEnabled(True)
            self.btn_load_blueprint.setEnabled(True)
            self.btn_save_blueprint.setEnabled(True)
            self.btn_sync_blueprint.setEnabled(True)
            self.btn_scan.setEnabled(True)
            self.btn_refresh_repos.setEnabled(True)
            return

        manager, pkg, cmd = self.upgrade_queue.pop(0)
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
        self.run_next_blueprint_sync()

    def closeEvent(self, event):
        """Prompt user on exit if active background child processes exist, then terminate them."""
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
            if reply == QMessageBox.Yes:
                coordinator.terminate_all()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
