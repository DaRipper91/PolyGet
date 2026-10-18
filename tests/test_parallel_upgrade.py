import sys
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication

from app.core.manager import PackageManager
from app.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def _mgr(name, cmd):
    m = MagicMock(spec=PackageManager)
    m.name = name
    m.asks_for_password = False
    m.get_upgrade_command.return_value = cmd
    return m


def test_batch_with_non_elevated_managers_starts_every_worker(qapp):
    """Regression: the parallel queue holds UpgradeTask objects, which can't be unpacked as
    (manager, packages) tuples. Any batch including npm/Flatpak/Cargo/Pipx raised TypeError and
    left the window stuck in "batch upgrade"."""
    with patch("app.ui.main_window.MainWindow.scan_all"):
        w = MainWindow()
    w.managers = {"DNF": _mgr("DNF", ["pkexec", "dnf", "upgrade", "-y"]),
                  "NPM": _mgr("NPM", ["npm", "update", "-g"]),
                  "Cargo": _mgr("Cargo", ["cargo", "install"])}
    started = []
    with patch.object(MainWindow, "_confirm_commands", return_value=True), \
            patch.object(MainWindow, "_start_upgrade_worker", lambda self, m, p: started.append((m.name, p))):
        w.start_batch_upgrade(targets={"DNF": ["firefox"], "NPM": ["typescript"], "Cargo": ["ripgrep"]})
    assert sorted(started) == [("Cargo", ["ripgrep"]), ("DNF", ["firefox"]), ("NPM", ["typescript"])]
    assert w._running_workers == 3
