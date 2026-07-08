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
