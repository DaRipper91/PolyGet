import sys
from unittest.mock import patch

import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from app.core.drivers.aur import AurManager
from app.core.drivers.npm import NpmManager
from app.ui.main_window import MainWindow, UpgradeTask
from app.ui.review_dialog import BuildScriptDialog, BuildScriptWorker, has_build_scripts


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


@pytest.fixture
def window(qapp):
    with patch("app.ui.main_window.MainWindow.scan_all"):
        yield MainWindow()


SCRIPT = {"url": "https://aur.archlinux.org/cgit/aur.git/plain/PKGBUILD?h=yay", "script": "pkgname=yay\nbuild() { make; }\n"}


def test_only_the_aur_has_scripts_to_review():
    assert has_build_scripts(AurManager())
    assert not has_build_scripts(NpmManager())


def test_dialog_blocks_proceeding_when_a_script_could_not_be_fetched(qapp):
    ok = BuildScriptDialog("AUR", {"yay": SCRIPT}, "Install")
    assert ok.btn_go.isEnabled() and ok.tabs.count() == 1
    bad = BuildScriptDialog("AUR", {"yay": SCRIPT, "nope": {"error": "not found in the AUR"}}, "Upgrade 2",
                            allow_skip=True)
    assert not bad.btn_go.isEnabled()
    assert bad.btn_skip is not None
    assert any(bad.tabs.tabText(i) == "⚠ nope" for i in range(bad.tabs.count()))


def test_worker_collects_scripts_and_errors(qapp):
    from app.core.manager import DriverError

    class FakeAur(AurManager):
        async def get_build_script(self, package):
            if package == "nope":
                raise DriverError("'nope' was not found in the AUR")
            return SCRIPT["url"], SCRIPT["script"]

    got = []
    worker = BuildScriptWorker(FakeAur(), ["yay", "nope"])
    worker.result_signal.connect(got.append)
    worker.run()
    assert got[0]["yay"] == SCRIPT and "not found" in got[0]["nope"]["error"]


def test_store_install_of_an_aur_package_shows_the_script_first(window):
    with patch.object(AurManager, "is_available", return_value=True), \
            patch("app.core.drivers.aur._helper", return_value="paru"), patch.object(QThread, "start"):
        window.install_package({"id": "yay", "name": "yay", "source": "AUR"})
    worker = window.active_workers[-1]
    assert isinstance(worker, BuildScriptWorker) and worker.packages == ["yay"]
    assert "AUR:yay" in window.installing_packages  # double clicks wait

    with patch.object(BuildScriptDialog, "exec", return_value=QDialog.DialogCode.Accepted), \
            patch.object(AurManager, "is_available", return_value=True), \
            patch("app.core.drivers.aur._helper", return_value="paru"), \
            patch("app.ui.main_window.QMessageBox.question") as question, patch.object(QThread, "start"):
        window._install_after_review({"id": "yay", "name": "yay", "source": "AUR"}, AurManager(),
                                     ["paru", "-S", "--noconfirm", "yay"], {"yay": SCRIPT})
    assert not question.called  # the review was the confirmation
    assert window.active_workers[-1].cmd == ["paru", "-S", "--noconfirm", "yay"]


def _batch_window(window):
    aur, npm = AurManager(), NpmManager()
    window.managers = {"AUR": aur, "NPM": npm}
    return aur, npm


def test_batch_upgrade_with_aur_packages_reviews_before_confirming(window):
    _batch_window(window)
    with patch("app.core.drivers.aur._helper", return_value="paru"), patch.object(QThread, "start"), \
            patch.object(MainWindow, "_confirm_commands") as confirm:
        window.start_batch_upgrade(targets={"AUR": ["yay"], "NPM": ["typescript"]})
    assert not confirm.called
    assert isinstance(window.active_workers[-1], BuildScriptWorker)
    assert window.active_operation is None


def test_skipping_aur_in_review_upgrades_the_rest(window):
    _batch_window(window)
    with patch.object(BuildScriptDialog, "exec", return_value=BuildScriptDialog.SKIP), \
            patch.object(MainWindow, "start_batch_upgrade") as start:
        window._upgrade_after_review("AUR", {"AUR": ["yay"], "NPM": ["typescript"]}, frozenset(), {"yay": SCRIPT})
    assert start.call_args.kwargs == {"targets": {"NPM": ["typescript"]}, "reviewed": frozenset()}


def test_accepting_review_continues_with_aur_marked_reviewed(window):
    _batch_window(window)
    with patch.object(BuildScriptDialog, "exec", return_value=QDialog.DialogCode.Accepted), \
            patch.object(MainWindow, "start_batch_upgrade") as start:
        window._upgrade_after_review("AUR", {"AUR": ["yay"]}, frozenset(), {"yay": SCRIPT})
    assert start.call_args.kwargs == {"targets": {"AUR": ["yay"]}, "reviewed": frozenset({"AUR"})}


def test_reviewed_aur_goes_straight_to_the_command_confirm(window):
    _batch_window(window)
    with patch("app.core.drivers.aur._helper", return_value="paru"), \
            patch.object(MainWindow, "_confirm_commands", return_value=False) as confirm:
        window.start_batch_upgrade(targets={"AUR": ["yay"]}, reviewed=frozenset({"AUR"}))
    assert confirm.called
