import sys
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


class Recorder:
    def __init__(self):
        self.sent = []

    def notify(self, key, title, body="", actions=(), urgency=1, progress=None):
        self.sent.append((key, title, body))

    def close(self, key):
        pass


@pytest.fixture
def window(qapp):
    with patch("app.ui.main_window.MainWindow.scan_all"):
        w = MainWindow()
    w.notifier = Recorder()
    return w


YES = {"needed": True, "method": "dnf needs-restarting -r", "reasons": ["kernel", "glibc"]}


def test_definite_yes_after_an_upgrade_shows_banner_and_notifies(window):
    window._show_restart(YES, "", after_upgrade=True)
    assert not window.restart_banner.isHidden()
    assert window.restart_label.text() == "Restart needed to finish updating: kernel (+1 more)"
    assert window.notifier.sent == [("restart", "Restart to finish updating", "kernel")]


@pytest.mark.parametrize("result,error", [({"needed": None, "method": "none available", "reasons": []}, ""),
                                          ({"needed": False, "method": "x", "reasons": []}, ""),
                                          (None, "boom")])
def test_cant_tell_no_or_error_shows_nothing(window, result, error):
    window._show_restart(result, error, after_upgrade=True)
    assert window.restart_banner.isHidden() and window.notifier.sent == []


def test_startup_check_is_quiet_and_dismissal_sticks(window):
    window._show_restart(YES, "", after_upgrade=False)
    assert not window.restart_banner.isHidden() and window.notifier.sent == []
    window.dismiss_restart_notice()
    window._show_restart(YES, "", after_upgrade=False)
    assert window.restart_banner.isHidden()
    window._show_restart(YES, "", after_upgrade=True)  # a new upgrade brings it back
    assert not window.restart_banner.isHidden()


def test_report_with_upgrades_triggers_a_restart_check(window):
    window.updates_cache = {"NPM": []}
    with patch.object(MainWindow, "check_restart") as check, \
            patch("app.ui.main_window.QMessageBox.information"), \
            patch("app.core.history_store.record_upgrade"):  # keep the shared test history clean
        window.report_upgrade_results({"NPM": (["typescript"], True)})
    check.assert_called_once_with(after_upgrade=True)
