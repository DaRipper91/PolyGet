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


def test_gui_package_managers_page(qapp):
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


def test_gui_repositories_page(qapp):
    """Test the Repositories UI page population and actions."""
    from app.ui.main_window import MainWindow, RepoItemWidget, FetchReposWorker
    from PySide6.QtCore import QThread
    from unittest.mock import MagicMock, patch

    window = MainWindow()

    # 1. Switch to Repositories tab (index 5)
    window.nav_list.setCurrentRow(5)
    
    # Check that managers listing is populated with at least DNF/Flatpak
    assert window.repos_mgr_list.count() > 0
    assert "DNF" in [window.repos_mgr_list.item(i).text() for i in range(window.repos_mgr_list.count())]

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

