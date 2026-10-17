import sys
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QMessageBox

from app.core.distro import get_distro_family, get_system_manager_name
from app.core.drivers.flatpak import FlatpakManager
from app.core.manager import PackageManager
from app.ui.main_window import MainWindow


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


def _driver(name, cmd, available=True):
    drv = MagicMock(spec=PackageManager)
    drv.name = name
    drv.is_available.return_value = available
    drv.get_install_command_for.return_value = cmd
    return drv


@patch("app.ui.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes)
def test_store_install_uses_the_drivers_command(mock_question, window):
    """Any source the driver layer knows installs through its own command, not a GUI copy."""
    drv = _driver("Pacman", ["pkexec", "pacman", "-S", "--noconfirm", "gimp"])
    item = {"id": "gimp", "name": "GIMP", "source": "Pacman"}
    with patch("app.core.manager.get_all_managers", return_value=[drv]), patch.object(QThread, "start"):
        window.install_package(item)
    drv.get_install_command_for.assert_called_once_with(item)
    assert window.active_workers[-1].cmd == ["pkexec", "pacman", "-S", "--noconfirm", "gimp"]


@patch("app.ui.main_window.QMessageBox.critical")
def test_store_install_refuses_a_manager_that_is_not_installed(mock_critical, window):
    drv = _driver("DNF", ["pkexec", "dnf", "install", "-y", "gimp"], available=False)
    with patch("app.core.manager.get_all_managers", return_value=[drv]), patch.object(QThread, "start"):
        window.install_package({"id": "gimp", "name": "GIMP", "source": "DNF"})
    assert mock_critical.called
    assert window.active_workers == []
    assert window.installing_packages == set()


def test_flatpak_install_keeps_the_results_remote():
    mgr = FlatpakManager()
    assert mgr.get_install_command_for({"id": "org.gimp.GIMP", "remote": "fedora"}) == [
        "flatpak", "install", "-y", "fedora", "org.gimp.GIMP"]
    assert mgr.get_install_command_for({"id": "org.gimp.GIMP"}) == [
        "flatpak", "install", "-y", "org.gimp.GIMP"]


@pytest.mark.parametrize("os_id,expected", [("fedora", "DNF"), ("cachyos", "Pacman"),
                                            ("ubuntu", "APT"), ("alpine", None)])
def test_system_manager_follows_the_distro_family(os_id, expected):
    get_distro_family.cache_clear()
    try:
        with patch("app.core.distro._os_release", return_value={"ID": os_id}):
            assert get_system_manager_name() == expected
    finally:
        get_distro_family.cache_clear()


def _remover(name="DNF", cmd=("pkexec", "dnf", "remove", "-y", "gtk3")):
    drv = MagicMock(spec=PackageManager)
    drv.name = name
    drv.is_available.return_value = True
    drv.get_remove_command.return_value = list(cmd)
    return drv


def test_remove_previews_before_running_anything(window):
    drv = _remover()
    window.managers["DNF"] = drv
    with patch.object(QThread, "start"):
        window.remove_package("DNF", "gtk3")
    worker = window.active_workers[-1]
    assert worker.__class__.__name__ == "RemovePreviewWorker" and worker.package == "gtk3"
    assert "DNF:gtk3" in window.removing_packages

    with patch.object(QThread, "start"):
        window.remove_package("DNF", "gtk3")  # double click while previewing
    assert len(window.active_workers) == 1


@patch("app.ui.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes)
def test_confirm_lists_what_else_goes_and_runs_the_drivers_command(mock_question, window):
    drv = _remover()
    window.removing_packages.add("DNF:gtk3")
    with patch.object(QThread, "start"):
        window._confirm_remove(drv, "gtk3", ["pkexec", "dnf", "remove", "-y", "gtk3"],
                               {"remove": ["gtk3", "gimp", "evince"], "blocked_by": []}, "")
    text = mock_question.call_args[0][2]
    assert "also removes 2 other package(s)" in text and "gimp" in text and "evince" in text
    assert "pkexec dnf remove -y gtk3" in text
    assert window.active_workers[-1].cmd == ["pkexec", "dnf", "remove", "-y", "gtk3"]


@patch("app.ui.main_window.QMessageBox.question")
@patch("app.ui.main_window.QMessageBox.warning")
def test_blocked_removal_is_explained_and_never_runs(mock_warning, mock_question, window):
    window.removing_packages.add("Pacman:gtk3")
    window._confirm_remove(_remover("Pacman"), "gtk3", ["pkexec", "pacman", "-Rs", "--noconfirm", "gtk3"],
                           {"remove": ["gtk3"], "blocked_by": ["gimp"]}, "")
    assert "gimp" in mock_warning.call_args[0][2]
    assert not mock_question.called
    assert window.active_workers == [] and window.removing_packages == set()


@patch("app.ui.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.No)
def test_failed_preview_warns_instead_of_claiming_nothing_else_goes(mock_question, window):
    window.removing_packages.add("DNF:gtk3")
    window._confirm_remove(_remover(), "gtk3", ["pkexec", "dnf", "remove", "-y", "gtk3"], None, "cache broken")
    text = mock_question.call_args[0][2]
    assert "couldn't check" in text and "Nothing else" not in text
    assert window.removing_packages == set()  # declined


@patch("app.ui.main_window.QMessageBox.information")
def test_successful_removal_drops_the_pending_update(mock_info, window):
    window.updates_cache = {"NPM": [{"name": "typescript", "current": "5.5", "new": "5.6"}]}
    window.selected_updates = {"NPM": {"typescript"}}
    window.removing_packages.add("NPM:typescript")
    window.handle_remove_finished(True, "NPM", "typescript")
    assert window.updates_cache["NPM"] == [] and window.selected_updates["NPM"] == set()
    assert window.removing_packages == set()


def test_store_installed_view_filters_and_offers_remove(window):
    window.chk_store_installed.blockSignals(True)
    window.chk_store_installed.setChecked(True)
    window.chk_store_installed.blockSignals(False)
    window.store_generation = 7
    window._show_installed_results({"NPM": ["typescript", "eslint"], "Cargo": ["ripgrep"]}, "type", 7)
    assert window.store_list.count() == 1
    row = window.store_list.itemWidget(window.store_list.item(0))
    assert row.item["installed"] and row.btn_install.text() == "Remove…"
