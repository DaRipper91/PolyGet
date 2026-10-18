import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

import app.core.settings_store as settings_store
from app.core.manager import PackageManager
from app.ui.main_window import MainWindow
from app.ui.notifier import CRITICAL, LOW


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


class Recorder:
    def __init__(self):
        self.sent, self.closed = [], []

    def notify(self, key, title, body="", actions=(), urgency=1, progress=None):
        self.sent.append(dict(key=key, title=title, body=body, actions=list(actions),
                              urgency=urgency, progress=progress))
        return True

    def close(self, key):
        self.closed.append(key)

    def service_available(self):
        return True


@pytest.fixture
def settings(tmp_path, monkeypatch):
    store = settings_store.SettingsStore(tmp_path / "settings.json")
    monkeypatch.setattr(settings_store, "_settings_instance", store)
    return store


@pytest.fixture
def window(qapp, settings):
    with patch("app.ui.main_window.MainWindow.scan_all"):
        w = MainWindow()
    w.notifier = Recorder()
    return w


def _mgr(name, cmd):
    m = MagicMock(spec=PackageManager)
    m.name = name
    m.category = "x"
    m.asks_for_password = False
    m.get_upgrade_command.return_value = cmd
    return m


def _background_scan(window, results, errors=None):
    window.notify_after_scan = True
    for name, ups in results.items():
        window.handle_scan_results(name, ups)
    for name, err in (errors or {}).items():
        window.handle_scan_error(name, err)
    window.update_tray_status()


UPS = {"DNF": [{"name": "firefox", "current": "131.0", "new": "132.0"},
               {"name": "mesa", "current": "24.1.7", "new": "24.2.4"}],
       "NPM": [{"name": "typescript", "current": "5.5.4", "new": "5.6.3"}]}


def test_new_updates_are_grouped_with_buttons(window):
    _background_scan(window, UPS)
    [n] = window.notifier.sent
    assert n["key"] == "updates" and n["title"] == "3 updates ready"
    assert n["body"].startswith("DNF 2 · NPM 1") and "firefox 132.0 is a major update" in n["body"]
    assert ("update-all", "Update all") in n["actions"]


def test_already_announced_updates_are_not_repeated(window):
    _background_scan(window, UPS)
    _background_scan(window, UPS)
    assert len(window.notifier.sent) == 1


def test_off_and_the_old_tray_switch(window, settings):
    settings.set("tray.notify", False)  # the pre-existing switch, never migrated
    _background_scan(window, UPS)
    assert window.notifier.sent == []


def test_only_major(window, settings):
    settings.set("notify.only_major", True)
    _background_scan(window, UPS)
    [n] = window.notifier.sent
    assert n["title"] == "1 update ready"


def test_quiet_hours_hold_then_release(window, settings):
    settings.set("notify.quiet_hours", True)
    settings.set("notify.quiet_start", 22)
    settings.set("notify.quiet_end", 8)
    with patch.object(MainWindow, "_in_quiet_hours", return_value=True):
        _background_scan(window, UPS, errors={"Cargo": "registry unreachable"})
    assert window.notifier.sent == []
    window._notification_tick(datetime(2026, 10, 18, 9, 0))
    titles = [n["title"] for n in window.notifier.sent]
    assert "Cargo scan failed" in titles and "While you were away: 3 updates" in titles


def test_quiet_hours_window_wraps_midnight(window, settings):
    settings.set("notify.quiet_hours", True)
    assert window._in_quiet_hours(datetime(2026, 1, 1, 23)) and window._in_quiet_hours(datetime(2026, 1, 1, 3))
    assert not window._in_quiet_hours(datetime(2026, 1, 1, 12))


def test_daily_digest_once_at_its_hour(window, settings):
    settings.set("notify.new_updates", "digest")
    settings.set("notify.digest_hour", 8)
    _background_scan(window, UPS)
    assert window.notifier.sent == []
    window._notification_tick(datetime(2026, 10, 18, 7, 59))
    window._notification_tick(datetime(2026, 10, 18, 8, 1))
    window._notification_tick(datetime(2026, 10, 18, 8, 30))
    [n] = window.notifier.sent
    assert n["title"] == "This morning: 3 updates" and ("review", "Review") in n["actions"]


def test_scan_failure_is_critical_with_retry_and_announced_once(window):
    _background_scan(window, {}, errors={"Cargo": "registry unreachable\ndetails"})
    _background_scan(window, {}, errors={"Cargo": "registry unreachable\ndetails"})
    [n] = window.notifier.sent
    assert n["title"] == "Cargo scan failed" and n["body"] == "registry unreachable"
    assert n["urgency"] == CRITICAL and ("retry-scan", "Retry") in n["actions"]


def test_upgrade_progress_password_and_done_when_window_is_not_in_front(window):
    window.managers = {"DNF": _mgr("DNF", ["pkexec", "dnf", "upgrade", "-y"]),
                       "NPM": _mgr("NPM", ["npm", "update", "-g"])}
    with patch.object(MainWindow, "_user_is_here", return_value=False), \
            patch("app.ui.main_window.ExecutionWorker"), patch.object(MainWindow, "_confirm_commands", return_value=True):
        window.start_batch_upgrade(targets={"DNF": ["firefox"], "NPM": ["typescript"]})
        sent = window.notifier.sent
        assert sent[0]["key"] == "upgrade" and sent[0]["progress"] == 0 and sent[0]["urgency"] == LOW
        assert any(n["key"] == "password" and n["title"].startswith("DNF may be waiting") for n in sent)
        window._handle_upgrade_worker_finished(True, "DNF", ["firefox"])
        assert "password" in window.notifier.closed
        assert window.notifier.sent[-1]["progress"] == 50
        window._notify_upgrade_report(2, ["DNF", "NPM"], [], False)
    assert window.notifier.sent[-1]["title"] == "Updated 2 packages"


def test_upgrade_problems_are_critical_with_retry(window):
    with patch.object(MainWindow, "_user_is_here", return_value=False):
        window._notify_upgrade_report(0, [], ["Failed: Cargo"], True)
    n = window.notifier.sent[-1]
    assert n["urgency"] == CRITICAL and ("retry-upgrade", "Retry") in n["actions"]


def test_nothing_when_the_user_is_watching(window):
    with patch.object(MainWindow, "_user_is_here", return_value=True):
        window._upgrade_total = 2
        window._notify_upgrade_progress()
        window._notify_upgrade_report(2, ["DNF"], [], False)
    assert window.notifier.sent == [] and "upgrade" in window.notifier.closed


def test_actions_route_to_the_right_place(window):
    with patch.object(MainWindow, "update_all") as update_all, patch.object(MainWindow, "show_from_tray"):
        window.on_notification_action("updates", "update-all")
        assert update_all.called
        window.on_notification_action("scan-failed", "show-log")
    from app.ui.main_window import PAGE_CONSOLE
    assert window.nav_list.currentRow() == PAGE_CONSOLE

    box = MagicMock()
    window._report_box = box
    with patch.object(MainWindow, "show_from_tray"):
        window.on_notification_action("upgrade", "retry-upgrade")
    box.done.assert_called_once_with(QMessageBox.StandardButton.Retry)
