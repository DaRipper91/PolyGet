from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from app.core.history_store import load_history
from app.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def window():
    QApplication.instance() or QApplication([])
    with patch.object(MainWindow, "scan_all", lambda self: None):
        yield MainWindow()


def test_upgrade_that_changed_nothing_is_reported_and_retried_alone(window):
    """After an upgrade, the rescan decides: an exit-0 run whose package is still outdated is
    'not upgraded', and Retry re-runs only that package plus managers whose command failed."""
    window.updates_cache = {
        "DNF": [{"name": "vhs", "current": "0.11.0", "new": "0.12.1"}],  # still outdated
        "Cargo": [],  # dua-cli really upgraded
        "NPM": [],
    }
    window.scan_errors = {}
    results = {
        "DNF": (["vhs", "curl"], True),
        "Cargo": (["dua-cli"], True),
        "NPM": (["pnpm"], False),  # command itself failed
    }
    box = MagicMock()
    box.exec.return_value = QMessageBox.StandardButton.Retry
    with patch("app.ui.main_window.QMessageBox", wraps=QMessageBox) as mb, \
         patch.object(window, "start_batch_upgrade") as retry:
        mb.return_value = box
        mb.StandardButton = QMessageBox.StandardButton
        mb.Icon = QMessageBox.Icon
        window.report_upgrade_results(results)

    retry.assert_called_once_with(retry={"NPM": ["pnpm"], "DNF": ["vhs"]})
    history = {r["manager"]: r for r in load_history()}
    assert history["DNF"]["success"] is False and history["DNF"]["not_upgraded"] == ["vhs"]
    assert history["Cargo"]["success"] is True
    assert history["NPM"]["success"] is False
