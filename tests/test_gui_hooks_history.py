import json
import sys
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QMessageBox

import app.core.settings_store as settings_store
from app.core import hooks, history_store
from app.core.manager import PackageManager
from app.ui.main_window import AsyncCallWorker, MainWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


@pytest.fixture
def settings(tmp_path, monkeypatch):
    store = settings_store.SettingsStore(tmp_path / "settings.json")
    monkeypatch.setattr(settings_store, "_settings_instance", store)
    monkeypatch.setattr(history_store, "_HISTORY_PATH", tmp_path / "history.jsonl")
    monkeypatch.setattr(history_store.record_removal, "__defaults__",
                        (tmp_path / "history.jsonl", None))
    monkeypatch.setattr(history_store.load_history, "__defaults__", (tmp_path / "history.jsonl", 200))
    monkeypatch.setattr(history_store.record_upgrade, "__defaults__", (tmp_path / "history.jsonl", None))
    return store


@pytest.fixture
def window(qapp, settings):
    with patch("app.ui.main_window.MainWindow.scan_all"):
        yield MainWindow()


class FakeWorker:
    """Stands in for ExecutionWorker: records the command; tests decide when it finishes."""
    runs: list = []

    def __init__(self, cmd):
        self.cmd = cmd
        self.log_signal = MagicMock()
        self.finished = MagicMock()
        self._done = None
        self.finished_signal = MagicMock()
        self.finished_signal.connect.side_effect = lambda cb: setattr(self, "_done", cb)
        FakeWorker.runs.append(self)

    def start(self):
        pass


@pytest.fixture
def workers(monkeypatch):
    FakeWorker.runs = []
    monkeypatch.setattr("app.ui.main_window.ExecutionWorker", FakeWorker)
    return FakeWorker.runs


def _mgr(name, cmd):
    m = MagicMock(spec=PackageManager)
    m.name = name
    m.asks_for_password = False
    m.get_upgrade_command.return_value = cmd
    return m


def test_upgrade_runs_pre_hook_first_and_shows_hooks_in_confirm(window, settings, workers):
    hooks.add_hook("pre", ["snapper", "create", "-d", "polyget"], ["DNF"], ["upgrade"])
    hooks.add_hook("post", ["flatpak", "repair"])
    window.managers = {"DNF": _mgr("DNF", ["pkexec", "dnf", "upgrade", "-y", "firefox"])}
    with patch.object(MainWindow, "_confirm_commands", return_value=True) as confirm:
        window.start_batch_upgrade(targets={"DNF": ["firefox"]})
    shown = confirm.call_args[0][1]
    assert shown[0] == ["snapper", "create", "-d", "polyget"] and shown[-1] == ["flatpak", "repair"]
    assert [w.cmd for w in workers] == [["snapper", "create", "-d", "polyget"]]  # nothing else yet
    workers[0]._done(True)
    assert workers[-1].cmd == ["pkexec", "dnf", "upgrade", "-y", "firefox"]


def test_failed_pre_hook_upgrades_nothing(window, settings, workers):
    hooks.add_hook("pre", ["false"])
    window.managers = {"NPM": _mgr("NPM", ["npm", "update", "-g", "typescript"])}
    with patch.object(MainWindow, "_confirm_commands", return_value=True), \
            patch("app.ui.main_window.QMessageBox.warning") as warn:
        window.start_batch_upgrade(targets={"NPM": ["typescript"]})
        workers[0]._done(False)
    assert [w.cmd for w in workers] == [["false"]]
    assert "nothing was upgraded" in warn.call_args[0][2]
    assert window.active_operation is None and window.btn_scan.isEnabled()


def test_post_hooks_run_before_the_rescan_and_failures_are_reported(window, settings, workers):
    hooks.add_hook("post", ["first"])
    hooks.add_hook("post", ["second"])
    window.managers = {"NPM": _mgr("NPM", ["npm", "update", "-g", "typescript"])}
    with patch.object(MainWindow, "_confirm_commands", return_value=True), \
            patch.object(MainWindow, "scan_all") as rescan:
        window.start_batch_upgrade(targets={"NPM": ["typescript"]})
        workers[0]._done(True)                      # npm finished
        assert [w.cmd for w in workers[1:]] == [["first"]] and not rescan.called
        workers[1]._done(False)                     # post-hooks keep going after a failure
        workers[2]._done(True)
        assert rescan.called
    assert window._hook_failures == ["first"]
    with patch("app.ui.main_window.QMessageBox.exec", return_value=QMessageBox.StandardButton.Close):
        window.report_upgrade_results({"NPM": (["typescript"], True)})
    assert window._hook_failures == []


def test_removal_runs_hooks_verifies_and_logs_history(window, settings, workers):
    hooks.add_hook("pre", ["snap-it"], operations=["remove"])
    hooks.add_hook("post", ["after-it"], operations=["remove"])
    drv = _mgr("NPM", [])
    drv.get_remove_command.return_value = ["npm", "uninstall", "-g", "typescript"]
    window.removing_packages.add("NPM:typescript")
    with patch("app.ui.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes) as q:
        window._confirm_remove(drv, "typescript", ["npm", "uninstall", "-g", "typescript"], None, "")
    assert "snap-it" in q.call_args[0][2] and "after-it" in q.call_args[0][2]
    workers[0]._done(True)                                     # pre-hook ok -> removal starts
    assert workers[1].cmd == ["npm", "uninstall", "-g", "typescript"]
    with patch.object(QThread, "start"):
        workers[1]._done(True)                                 # removal ok -> verification
    verify = window.active_workers[-1]
    assert isinstance(verify, AsyncCallWorker)
    with patch("app.ui.main_window.QMessageBox.warning") as warn:
        verify.result_signal.emit(["typescript"], "")          # still installed!
        workers[2]._done(True)                                 # post-hook
    assert "still installed" in warn.call_args[0][2]
    [entry] = history_store.load_history()
    assert entry["action"] == "remove" and entry["success"] is False and entry["not_removed"] == ["typescript"]


def test_history_page_says_what_each_entry_was(window, settings):
    history_store.record_upgrade("DNF", ["firefox"], True, path=history_store._HISTORY_PATH)
    history_store.record_removal("NPM", ["typescript"], True)
    window.populate_history_page()
    rows = [window.history_list.item(i).text() for i in range(window.history_list.count())]
    assert "Removed" in rows[0] and "NPM: typescript" in rows[0]       # newest first
    assert "Upgraded" in rows[1] and "DNF: firefox" in rows[1]


def test_settings_can_add_and_remove_hooks(window, settings):
    from PySide6.QtWidgets import QComboBox, QLineEdit, QPushButton
    window.populate_settings_page()
    cmd = next(e for e in window.findChildren(QLineEdit) if e.accessibleName() == "Hook command")
    cmd.setText("pkexec snapper create -d 'before polyget'")
    next(b for b in window.findChildren(QPushButton) if b.text() == "Add hook").click()
    assert hooks.load_hooks()[0]["command"] == ["pkexec", "snapper", "create", "-d", "before polyget"]
