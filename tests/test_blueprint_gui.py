import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication
from app.core.manager import PackageManager
from app.ui.main_window import FetchInstalledWorker, MainWindow


@pytest.fixture(scope="session")
def qapp():
    """Fixture to initialize QApplication for Qt tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def test_fetch_installed_worker(qapp):
    """Test FetchInstalledWorker queries managers asynchronously and emits results."""
    mock_manager = MagicMock(spec=PackageManager)
    mock_manager.name = "TestManager"
    mock_manager.list_installed = AsyncMock(return_value=["pkg1", "pkg2"])

    worker = FetchInstalledWorker([mock_manager])
    
    results = {}
    def on_result(res):
        results.update(res)

    worker.result_signal.connect(on_result)
    
    # Run synchronously to avoid threading race in tests
    worker.run()

    assert "TestManager" in results
    assert results["TestManager"] == ["pkg1", "pkg2"]
    mock_manager.list_installed.assert_called_once()


@patch("app.ui.main_window.MainWindow.scan_all")
@patch("app.ui.main_window.discover_managers")
def test_export_local_configuration(mock_discover, mock_scan, qapp):
    """Test MainWindow.export_local_configuration starts worker and generates YAML."""
    mock_manager = MagicMock(spec=PackageManager)
    mock_manager.name = "Flatpak"
    mock_manager.list_installed = AsyncMock(return_value=["org.mozilla.firefox"])
    mock_discover.return_value = [mock_manager]

    window = MainWindow()
    
    # Mock QThread.start to run synchronously
    with patch.object(QThread, "start") as mock_start:
        def sync_run():
            # Find the active FetchInstalledWorker
            for w in window.active_workers:
                if isinstance(w, FetchInstalledWorker):
                    w.run()
                    w.finished.emit()
            
        mock_start.side_effect = sync_run
        
        # Trigger export
        window.export_local_configuration()

    # Verify editor content contains generated blueprint YAML
    editor_text = window.blueprint_editor.toPlainText()
    assert "Flatpak:" in editor_text
    assert "- org.mozilla.firefox" in editor_text
    assert "Blueprint generated successfully." in window.blueprint_status.text()


@patch("app.ui.main_window.MainWindow.scan_all")
@patch("app.ui.main_window.QFileDialog.getOpenFileName")
def test_load_blueprint_file(mock_get_open, mock_scan, tmp_path, qapp):
    """Test loading a blueprint file displays its contents in the editor."""
    blueprint_file = tmp_path / "test_blueprint.yaml"
    blueprint_content = "Flatpak:\n  - org.gimp.GIMP\n"
    blueprint_file.write_text(blueprint_content, encoding="utf-8")

    mock_get_open.return_value = (str(blueprint_file), "YAML Files (*.yaml)")

    window = MainWindow()
    window.load_blueprint_file()

    assert window.blueprint_editor.toPlainText() == blueprint_content
    assert "Loaded blueprint" in window.blueprint_status.text()


@patch("app.ui.main_window.MainWindow.scan_all")
@patch("app.ui.main_window.QFileDialog.getSaveFileName")
def test_save_blueprint_file(mock_get_save, mock_scan, tmp_path, qapp):
    """Test saving editor contents to a blueprint file."""
    save_file = tmp_path / "saved_blueprint.yaml"
    mock_get_save.return_value = (str(save_file), "YAML Files (*.yaml)")

    window = MainWindow()
    window.blueprint_editor.setPlainText("DNF:\n  - git\n")
    window.save_blueprint_file()

    assert save_file.exists()
    assert save_file.read_text(encoding="utf-8") == "DNF:\n  - git"
    assert "Saved blueprint" in window.blueprint_status.text()


@patch("app.ui.main_window.MainWindow.scan_all")
@patch("app.ui.main_window.discover_managers")
@patch("app.ui.main_window.QMessageBox.question")
@patch("app.ui.main_window.QMessageBox.information")
def test_sync_system_to_blueprint_no_drift(mock_info, mock_question, mock_discover, mock_scan, qapp):
    """Test blueprint sync when there is no drift (packages already installed)."""
    mock_manager = MagicMock(spec=PackageManager)
    mock_manager.name = "Flatpak"
    mock_manager.list_installed = AsyncMock(return_value=["org.mozilla.firefox"])
    mock_discover.return_value = [mock_manager]

    window = MainWindow()
    window.blueprint_editor.setPlainText("Flatpak:\n  - org.mozilla.firefox\n")
    
    # Mock QThread.start to run synchronously
    with patch.object(QThread, "start") as mock_start:
        def sync_run():
            for w in window.active_workers:
                if isinstance(w, FetchInstalledWorker):
                    w.run()
                    w.finished.emit()
            
        mock_start.side_effect = sync_run
        
        # Trigger sync
        window.sync_system_to_blueprint()

    # No drift, so message box shouldn't be opened, and state should be in sync
    mock_question.assert_not_called()
    mock_info.assert_called_once()
    assert "System is in sync" in window.blueprint_status.text()


def test_store_search_npm_cargo(qapp):
    """Test SearchWorker querying npm search and cargo search concurrently."""
    from app.ui.main_window import SearchWorker

    mock_cargo_proc = AsyncMock()
    mock_cargo_proc.returncode = 0
    mock_cargo_proc.communicate.return_value = (
        b'ripgrep = "13.0.0" # Fast search utility\n',
        b""
    )

    mock_npm_proc = AsyncMock()
    mock_npm_proc.returncode = 0
    mock_npm_proc.communicate.return_value = (
        b'[\n'
        b'  {\n'
        b'    "name" : "typescript",\n'
        b'    "description" : "compiler",\n'
        b'    "version" : "4.5.2"\n'
        b'  }\n'
        b']\n',
        b""
    )

    def mock_exec(*args, **kwargs):
        if "cargo" in args:
            return mock_cargo_proc
        elif "npm" in args:
            return mock_npm_proc
        return AsyncMock()

    # Search both cargo and npm
    worker = SearchWorker("test-query", source_filter="All")
    
    results = []
    def on_results(res):
        results.extend(res)

    worker.results_signal.connect(on_results)

    with patch("shutil.which", return_value="/usr/bin/mock"), \
         patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        worker.run()

    # Verify that both Cargo and NPM search results were aggregated
    sources = [item["source"] for item in results]
    assert "Cargo" in sources
    assert "NPM" in sources

    # Verify Cargo item details
    cargo_item = [x for x in results if x["source"] == "Cargo"][0]
    assert cargo_item["name"] == "ripgrep"
    assert cargo_item["version"] == "13.0.0"

    # Verify NPM item details
    npm_item = [x for x in results if x["source"] == "NPM"][0]
    assert npm_item["name"] == "typescript"
    assert npm_item["version"] == "4.5.2"


def test_store_search_pipx(qapp):
    """Test SearchWorker querying Pipx exact package lookup via PyPI JSON API."""
    from app.ui.main_window import SearchWorker

    mock_pipx_proc = AsyncMock()
    mock_pipx_proc.returncode = 0
    mock_pipx_proc.communicate.return_value = (
        b'{\n'
        b'  "info": {\n'
        b'    "name": "black",\n'
        b'    "summary": "The uncompromising code formatter.",\n'
        b'    "version": "22.3.0"\n'
        b'  }\n'
        b'}\n',
        b""
    )

    def mock_exec(*args, **kwargs):
        if "curl" in args:
            return mock_pipx_proc
        return AsyncMock()

    # Search pipx
    worker = SearchWorker("black", source_filter="Pipx")
    
    results = []
    def on_results(res):
        results.extend(res)

    worker.results_signal.connect(on_results)

    with patch("shutil.which", return_value="/usr/bin/mock"), \
         patch("app.core.drivers.pipx.PipxManager._ensure_index_cached", return_value=["black"]), \
         patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        worker.run()

    assert len(results) == 1
    assert results[0]["source"] == "Pipx"
    assert results[0]["name"] == "black"
    assert results[0]["version"] == "22.3.0"
    assert results[0]["description"] == "The uncompromising code formatter."


def test_scan_worker_concurrent(qapp):
    """Test ScanWorker queries all package manager scans concurrently."""
    from app.ui.main_window import ScanWorker
    from app.core.drivers.flatpak import FlatpakManager
    from unittest.mock import AsyncMock, patch

    mgr1 = FlatpakManager()
    mgr1.check_updates = AsyncMock(return_value=[])

    worker = ScanWorker([mgr1])
    results = {}
    
    def on_updates(name, ups):
        results[name] = ups

    worker.updates_signal.connect(on_updates)
    worker.run()

    assert "Flatpak" in results


def test_scan_worker_reports_errors(qapp):
    """A failed manager scan must emit an error instead of an empty success result."""
    from app.ui.main_window import ScanWorker

    manager = MagicMock(spec=PackageManager)
    manager.name = "BrokenManager"
    manager.check_updates = AsyncMock(side_effect=RuntimeError("registry unavailable"))
    worker = ScanWorker([manager])
    errors = []
    updates = []
    worker.error_signal.connect(lambda name, message: errors.append((name, message)))
    worker.updates_signal.connect(lambda name, result: updates.append((name, result)))

    worker.run()

    assert errors == [("BrokenManager", "registry unavailable")]
    assert updates == []


@patch("app.ui.main_window.MainWindow.scan_all")
def test_main_window_scan_error_is_not_up_to_date(mock_scan, qapp):
    """The GUI should expose scan failures in its summary rather than claiming success."""
    window = MainWindow()
    window.managers["BrokenManager"] = MagicMock(category="Language/Dev")
    window.selected_updates["BrokenManager"] = set()
    window.status_list.addItem("🔍 BrokenManager - Connecting...")
    window.scan_generation = 4

    window.handle_scan_error("BrokenManager", "registry unavailable", generation=4)

    assert "Scan failed" in window.lbl_summary.text()
    assert "Up to date" not in window.lbl_summary.text()


@patch("app.ui.main_window.MainWindow.scan_all")
def test_handle_store_results_discards_stale_generation(mock_scan, qapp):
    """A slow, now-stale search must not overwrite a faster, newer one (audit finding B5)."""
    window = MainWindow()
    window.store_generation = 2

    new_item = {"name": "new-result", "id": "new-result", "source": "Flatpak",
                "description": "", "version": "", "icon": ""}
    stale_item = {"name": "stale-result", "id": "stale-result", "source": "Flatpak",
                  "description": "", "version": "", "icon": ""}

    # Newer search (generation 2) resolves first.
    window.handle_store_results([new_item], 2)
    first_pass_text = window.lbl_store_results.text()
    assert "1 package" in first_pass_text

    # Older, slower search (generation 1) arrives late and must be dropped.
    window.handle_store_results([stale_item], 1)
    assert window.lbl_store_results.text() == first_pass_text


@patch("app.ui.main_window.MainWindow.scan_all")
def test_display_repos_list_discards_stale_generation(mock_scan, qapp):
    """A slow, now-stale repo fetch must not overwrite a newer one (audit finding B5)."""
    window = MainWindow()
    dnf_mgr = MagicMock(spec=PackageManager)
    dnf_mgr.name = "DNF"
    flatpak_mgr = MagicMock(spec=PackageManager)
    flatpak_mgr.name = "Flatpak"

    window.repos_generation = 2
    window.repos_selected_manager = "DNF"

    # Newer, currently-selected manager's result lands first.
    window.display_repos_list([{"id": "fedora", "name": "Fedora", "url": "", "enabled": True}], dnf_mgr, 2)
    assert window.repos_list_widget.count() == 1

    # A slower fetch for a manager the user has since navigated away from arrives late.
    window.display_repos_list([{"id": "flathub", "name": "Flathub", "url": "", "enabled": True}], flatpak_mgr, 1)
    assert window.repos_list_widget.count() == 1


@patch("app.ui.main_window.MainWindow.scan_all")
def test_install_manager_backend_blocks_duplicate_launch(mock_scan, qapp):
    """A second click on the same manager's Install button must not spawn a second
    concurrent privileged install subprocess (audit finding B7)."""
    from app.core.catalog import CatalogEntry

    window = MainWindow()
    entry = CatalogEntry(
        id="paru", name="paru", category="System", description="", icon="", binary="paru",
        has_driver=False, self_install={"arch": ["pkexec", "pacman", "-S", "--noconfirm", "paru"]}
    )

    with patch("app.core.catalog.get_distro_family", return_value="arch"), \
         patch.object(QThread, "start"):
        window.install_manager_backend(entry)
        window.install_manager_backend(entry)

    assert len(window.active_workers) == 1
    assert "paru" in window.installing_managers

    window.handle_manager_install_finished(True, entry.name)
    assert "paru" not in window.installing_managers


@patch("app.ui.main_window.MainWindow.scan_all")
@patch("app.ui.main_window.QMessageBox.question")
@patch("app.ui.main_window.QMessageBox.information")
def test_install_package_blocks_duplicate_launch(mock_info, mock_question, mock_scan, qapp):
    """A second click on the same store result's Install button must not spawn a second
    concurrent install subprocess (audit finding B7)."""
    from PySide6.QtWidgets import QMessageBox as QMB
    mock_question.return_value = QMB.StandardButton.Yes

    window = MainWindow()
    item = {"id": "org.gimp.GIMP", "name": "GIMP", "source": "Flatpak", "remote": "flathub"}

    with patch.object(QThread, "start"):
        window.install_package(item)
        window.install_package(item)

    assert len(window.active_workers) == 1
    assert "Flatpak:org.gimp.GIMP" in window.installing_packages

    window.handle_install_finished(True, item["name"], "Flatpak:org.gimp.GIMP")
    assert "Flatpak:org.gimp.GIMP" not in window.installing_packages


@patch("app.ui.main_window.MainWindow.scan_all")
def test_toggle_repository_source_blocks_duplicate_launch(mock_scan, qapp):
    """A second click on the same repo's enable/disable action must not spawn a second
    concurrent subprocess (audit finding B7)."""
    window = MainWindow()
    mgr = MagicMock(spec=PackageManager)
    mgr.name = "Flatpak"
    mgr.get_remove_repo_command.return_value = ["flatpak", "remote-delete", "flathub"]

    with patch.object(QThread, "start"):
        window.toggle_repository_source(mgr, "flathub", False)
        window.toggle_repository_source(mgr, "flathub", False)

    assert len(window.active_workers) == 1
    assert "flathub" in window.repo_actions_in_flight

    window.handle_repo_action_finished(True, "flathub", "modified")
    assert "flathub" not in window.repo_actions_in_flight


@patch("app.ui.main_window.MainWindow.scan_all")
@patch("app.ui.main_window.discover_managers")
@patch("app.ui.main_window.QMessageBox.question")
@patch("app.ui.main_window.QMessageBox.information")
def test_blueprint_version_pinning(mock_info, mock_question, mock_discover, mock_scan, qapp):
    """Test blueprint sync with version pinning (e.g. package==version or package@version)."""
    mock_manager = MagicMock(spec=PackageManager)
    mock_manager.name = "Flatpak"
    # Firefox is installed
    mock_manager.list_installed = AsyncMock(return_value=["org.mozilla.firefox"])
    mock_discover.return_value = [mock_manager]

    window = MainWindow()
    # Pinned package matching firefox name, and non-installed pinned package
    window.blueprint_editor.setPlainText(
        "Flatpak:\n"
        "  - org.mozilla.firefox==120.0\n"
        "  - org.kde.kate@26.04.3\n"
    )
    
    # Mock QThread.start to run synchronously
    with patch.object(QThread, "start") as mock_start:
        def sync_run():
            for w in window.active_workers:
                if isinstance(w, FetchInstalledWorker):
                    w.run()
                    w.finished.emit()
            
        mock_start.side_effect = sync_run
        
        # Trigger sync
        window.sync_system_to_blueprint()

    # org.kde.kate@26.04.3 is missing, so mock_question should be called to confirm install.
    # org.mozilla.firefox==120.0 should not be flagged as missing since base_name "org.mozilla.firefox" is installed.
    mock_question.assert_called_once()
    args, kwargs = mock_question.call_args
    confirm_text = args[2]
    assert "org.kde.kate@26.04.3" in confirm_text
    assert "org.mozilla.firefox" not in confirm_text


@patch("app.ui.main_window.MainWindow.scan_all")
@patch("app.ui.main_window.discover_managers")
@patch("app.ui.main_window.QMessageBox.question")
@patch("app.ui.main_window.QMessageBox.information")
def test_sync_system_to_blueprint_with_drift(mock_info, mock_question, mock_discover, mock_scan, qapp):
    """Test blueprint sync when there is drift (packages missing) and user confirms install."""
    mock_manager = MagicMock(spec=PackageManager)
    mock_manager.name = "Flatpak"
    # Firefox is NOT installed
    mock_manager.list_installed = AsyncMock(return_value=[])
    mock_manager.get_install_command = MagicMock(return_value=["flatpak", "install", "-y", "org.mozilla.firefox"])
    mock_discover.return_value = [mock_manager]

    from PySide6.QtWidgets import QMessageBox
    # User confirms installation
    mock_question.return_value = QMessageBox.StandardButton.Yes

    window = MainWindow()
    window.blueprint_editor.setPlainText("Flatpak:\n  - org.mozilla.firefox\n")
    
    # Mock QThread.start to run synchronously
    from app.ui.main_window import ExecutionWorker
    def mock_start(self_thread):
        if isinstance(self_thread, FetchInstalledWorker):
            self_thread.run()
            self_thread.finished.emit()
        elif isinstance(self_thread, ExecutionWorker):
            # Mock successful run
            with patch("asyncio.create_subprocess_exec") as mock_exec:
                mock_proc = AsyncMock()
                mock_proc.pid = 9999
                mock_proc.returncode = 0
                mock_proc.stdout = AsyncMock()
                mock_proc.stdout.readline = AsyncMock(side_effect=[b"Successfully installed org.mozilla.firefox", b""])
                mock_proc.wait = AsyncMock(return_value=0)
                mock_exec.return_value = mock_proc
                self_thread.run()
            self_thread.finished.emit()

    with patch.object(QThread, "start", mock_start):
        # Trigger sync
        window.sync_system_to_blueprint()

    # Should ask to install, then show complete
    mock_question.assert_called_once()
    mock_info.assert_called_once()
    assert "Sync complete" in window.blueprint_status.text()
    
    # Ensure command was run and logged
    log_content = window.console.toPlainText()
    assert "Scheduled 1 packages for installation" in log_content
    assert "Successfully installed org.mozilla.firefox" in log_content


@patch("app.ui.main_window.MainWindow.scan_all")
def test_gui_package_managers_page(mock_scan, qapp):
    """Test the Package Managers manager interface page population and install actions."""
    from app.ui.main_window import MainWindow, ManagerItemWidget
    from PySide6.QtCore import QThread
    from unittest.mock import MagicMock, patch

    window = MainWindow()

    # 1. Switch to Package Managers tab (index 4)
    window.nav_list.setCurrentRow(4)
    
    # 2. Check that the managers list was populated
    assert window.managers_list.count() > 0
    
    # Check that ManagerItemWidget instances exist in rows
    row_item = window.managers_list.item(0)
    row_widget = window.managers_list.itemWidget(row_item)
    assert isinstance(row_widget, ManagerItemWidget)
    assert row_widget.mgr_name != ""

    # 3. Test triggering install backend
    mock_start = MagicMock()
    row_widget.entry.get_self_install_command = MagicMock(return_value=["mock-install"])
    with patch.object(QThread, "start", mock_start):
        window.install_manager_backend(row_widget.entry)

    # Verify transition to console (row 2)
    assert window.nav_list.currentRow() == 2
    mock_start.assert_called_once()


@patch("app.ui.main_window.MainWindow.scan_all")
def test_gui_repositories_page(mock_scan, qapp):
    """Test the Repositories UI page population and actions."""
    from app.ui.main_window import MainWindow, RepoItemWidget, FetchReposWorker
    from PySide6.QtCore import QThread
    from unittest.mock import MagicMock, patch

    window = MainWindow()

    # Stub out discovery so this doesn't depend on which package managers
    # actually happen to be installed on the host running the tests.
    fake_repo_mgr = MagicMock()
    fake_repo_mgr.name = "FakeRepoMgr"
    fake_repo_mgr.supports_repos = True
    fake_repo_mgr.get_add_repo_command.return_value = ["mock-add-repo"]
    fake_repo_mgr.get_remove_repo_command.return_value = ["mock-remove-repo"]
    fake_non_repo_mgr = MagicMock()
    fake_non_repo_mgr.name = "FakeNonRepoMgr"
    fake_non_repo_mgr.supports_repos = False

    with patch("app.core.manager.discover_managers", return_value=[fake_repo_mgr, fake_non_repo_mgr]):
        # 1. Switch to Repositories tab (index 5)
        window.nav_list.setCurrentRow(5)

        # Check that managers listing is populated with only repo-capable managers
        assert window.repos_mgr_list.count() > 0
        listed = [window.repos_mgr_list.item(i).text() for i in range(window.repos_mgr_list.count())]
        assert "FakeRepoMgr" in listed
        assert "FakeNonRepoMgr" not in listed

    # 2. Mock FetchReposWorker.run to emit sample repo data synchronously
    sample_repos = [
        {"id": "mock-repo", "name": "Mock Repo", "url": "https://example.com", "enabled": True}
    ]
    
    def mock_run(self_worker):
        self_worker.result_signal.emit(sample_repos)

    def mock_thread_start(self_worker):
        self_worker.run()
        
    with patch.object(FetchReposWorker, "run", mock_run), \
         patch.object(QThread, "start", mock_thread_start):
        window.load_repos_for_selected_manager(0)
        
    assert window.repos_list_widget.count() == 1
    row_item = window.repos_list_widget.item(0)
    row_widget = window.repos_list_widget.itemWidget(row_item)
    assert isinstance(row_widget, RepoItemWidget)
    assert row_widget.repo_name == "Mock Repo"

    # 3. Test triggering add repo action
    window.txt_add_repo.setText("copr/test")
    mock_start = MagicMock()
    with patch.object(QThread, "start", mock_start):
        window.add_repository_source()

    assert window.nav_list.currentRow() == 2
    mock_start.assert_called_once()
