import sys
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import QApplication, QMessageBox

from app.core.janitor import target
from app.core.manager import DriverError, PackageManager
from app.ui.cleanup_page import CleanupPage, CleanupScanWorker, is_destructive
from app.ui.main_window import AsyncCallWorker, MainWindow, PAGE_CLEANUP


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


ORPHANS = target("DNF", "orphans", "Orphaned packages", ["pkexec", "dnf", "autoremove", "-y"], 1024 * 1024, ["libfoo"])
LEFTOVER = target("Flatpak", "leftover-data", "Data of uninstalled apps",
                  ["rm", "-rf", "--", "/home/u/.var/app/org.gone.App"], 10, ["org.gone.App"])


def test_page_lists_targets_unticks_data_deletion_and_shows_failures(qapp):
    page = CleanupPage()
    page.set_results({
        "DNF": {"ok": True, "result": [ORPHANS]},
        "Flatpak": {"ok": True, "result": [LEFTOVER]},
        "NPM": {"ok": False, "error": "npm cache verify failed"},
        "Cargo": {"ok": False, "unsupported": True},
    })
    rows = {page.tree.topLevelItem(i).text(1): page.tree.topLevelItem(i) for i in range(page.tree.topLevelItemCount())}
    assert set(rows) == {"DNF", "Flatpak", "NPM"}                 # unsupported managers aren't listed
    assert rows["DNF"].checkState(0) == Qt.CheckState.Checked
    assert rows["Flatpak"].checkState(0) == Qt.CheckState.Unchecked  # never ticked for you
    assert rows["Flatpak"].child(0).text(0) == "org.gone.App"
    assert rows["NPM"].text(0).startswith("Couldn't check")      # a failure, not "nothing to clean"
    assert "couldn't be checked" in page.summary.text()
    assert page.selected_targets() == [ORPHANS] and page.btn_clean.text() == "Clean 1 selected"


def test_scan_worker_separates_failures_from_unsupported(qapp):
    ok, bad, none = (MagicMock(spec=PackageManager) for _ in range(3))
    ok.name, bad.name, none.name = "DNF", "NPM", "Cargo"

    async def targets():
        return [ORPHANS]

    async def boom():
        raise DriverError("query failed")

    async def unsupported():
        raise NotImplementedError

    ok.get_cleanup_targets, bad.get_cleanup_targets, none.get_cleanup_targets = targets, boom, unsupported
    got = []
    worker = CleanupScanWorker([ok, bad, none])
    worker.result_signal.connect(got.append)
    worker.run()
    assert got[0]["DNF"] == {"ok": True, "result": [ORPHANS]}
    assert got[0]["NPM"] == {"ok": False, "error": "query failed"}
    assert got[0]["Cargo"] == {"ok": False, "unsupported": True}


def test_only_data_deletion_counts_as_destructive():
    assert is_destructive(LEFTOVER) and not is_destructive(ORPHANS)


@pytest.fixture
def window(qapp):
    with patch("app.ui.main_window.MainWindow.scan_all"):
        yield MainWindow()


def test_page_is_reachable_and_scans_on_first_visit(window):
    with patch.object(MainWindow, "scan_cleanup") as scan:
        window.nav_list.setCurrentRow(PAGE_CLEANUP)
    assert window.stacked_widget.currentWidget() is window.cleanup_page and scan.called


def test_cleaning_without_data_deletion_runs_each_command(window):
    with patch.object(MainWindow, "_confirm_commands", return_value=True), \
            patch.object(MainWindow, "_run_commands") as run:
        window.clean_targets([ORPHANS])
    assert run.call_args[0][0] == [ORPHANS["command"]]


def test_data_deletion_needs_its_own_confirmation(window):
    with patch.object(MainWindow, "_confirm_destructive", return_value=False), \
            patch.object(MainWindow, "_run_commands") as run, \
            patch.object(MainWindow, "_confirm_commands") as confirm:
        window.clean_targets([LEFTOVER])
    assert not confirm.called and not run.called


def test_data_deletion_stops_if_the_leftovers_changed_since_the_scan(window):
    flatpak = MagicMock(spec=PackageManager)
    flatpak.name = "Flatpak"
    with patch.object(MainWindow, "_confirm_destructive", return_value=True), \
            patch.object(MainWindow, "_confirm_commands", return_value=True), \
            patch.object(MainWindow, "_cleanup_managers", return_value=[flatpak]), \
            patch.object(QThread, "start"):
        window.clean_targets([LEFTOVER])
    recheck = window.active_workers[-1]
    assert isinstance(recheck, AsyncCallWorker)
    with patch.object(MainWindow, "_run_commands") as run, patch.object(MainWindow, "scan_cleanup"), \
            patch("app.ui.main_window.QMessageBox.warning") as warn:
        recheck.result_signal.emit({"Flatpak": []}, "")       # the app was reinstalled meanwhile
    assert not run.called and "changed since the scan" in warn.call_args[0][2]

    with patch.object(MainWindow, "_run_commands") as run:
        recheck.result_signal.emit({"Flatpak": [LEFTOVER]}, "")  # unchanged: go ahead
    assert run.call_args[0][0] == [LEFTOVER["command"]]


def test_destructive_dialog_needs_the_checkbox(window):
    shown = {}

    def fake_exec(box):
        yes = box.button(QMessageBox.StandardButton.Yes)
        shown["enabled_before"] = yes.isEnabled()
        box.checkBox().setChecked(True)
        shown["enabled_after"] = yes.isEnabled()
        shown["details"] = box.detailedText()
        return QMessageBox.StandardButton.Yes

    with patch.object(QMessageBox, "exec", fake_exec):
        assert window._confirm_destructive(LEFTOVER)
    assert shown == {"enabled_before": False, "enabled_after": True,
                     "details": "/home/u/.var/app/org.gone.App"}
