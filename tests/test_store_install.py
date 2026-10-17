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
