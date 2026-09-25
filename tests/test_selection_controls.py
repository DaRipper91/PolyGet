import sys
import pytest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from app.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    """Fixture to initialize QApplication for Qt tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


@patch("app.ui.main_window.MainWindow.scan_all")
def test_select_all_and_deselect_all_updates(mock_scan, qapp):
    """Test select_all_updates and deselect_all_updates manipulate selected_updates set."""
    window = MainWindow()
    window.updates_cache = {
        "Cargo": [{"name": "satty", "current": "v0.21.1", "new": "v0.22.0"}],
        "DNF": [{"name": "librepo", "current": "Installed", "new": "1.21.0-2.fc44"}]
    }
    
    # Test Deselect All
    window.deselect_all_updates()
    assert window.selected_updates["Cargo"] == set()
    assert window.selected_updates["DNF"] == set()
    assert sum(len(s) for s in window.selected_updates.values()) == 0

    # Test Select All
    window.select_all_updates()
    assert window.selected_updates["Cargo"] == {"satty"}
    assert window.selected_updates["DNF"] == {"librepo"}
    assert sum(len(s) for s in window.selected_updates.values()) == 2
