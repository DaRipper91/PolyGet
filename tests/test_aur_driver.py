import asyncio
from unittest.mock import patch

import pytest

from app.core.drivers.aur import AurManager
from app.core.manager import DriverError


@pytest.fixture
def paru():
    with patch("app.core.drivers.aur.shutil.which", side_effect=lambda b: f"/usr/bin/{b}" if b == "paru" else None):
        yield


def test_helper_preference_and_availability():
    with patch("app.core.drivers.aur.shutil.which", side_effect=lambda b: f"/usr/bin/{b}" if b == "yay" else None):
        assert AurManager().is_available()
        assert AurManager().get_install_command("foo")[0] == "yay"
    with patch("app.core.drivers.aur.shutil.which", return_value=None):
        assert not AurManager().is_available()


def test_check_updates_parses_and_treats_exit_1_as_empty(paru, scripted_exec):
    scripted_exec.add("paru -Qua", stdout="foo-bin 1.0-1 -> 1.1-1\nbar-git r10 -> r12\n")
    assert asyncio.run(AurManager().check_updates()) == [
        {"name": "foo-bin", "current": "1.0-1", "new": "1.1-1"},
        {"name": "bar-git", "current": "r10", "new": "r12"},
    ]
    scripted_exec.rules.clear()
    scripted_exec.add("paru -Qua", rc=1)
    assert asyncio.run(AurManager().check_updates()) == []


def test_check_updates_real_failure_raises(paru, scripted_exec):
    scripted_exec.add("paru -Qua", rc=2, stderr="error: failed to synchronize")
    with pytest.raises(DriverError):
        asyncio.run(AurManager().check_updates())


def test_installed_uses_foreign_package_list(paru, scripted_exec):
    scripted_exec.add("pacman -Qm", stdout="foo-bin 1.0-1\nbar-git r10-1\n")
    assert asyncio.run(AurManager().list_installed_versions()) == {"foo-bin": "1.0-1", "bar-git": "r10-1"}
    assert asyncio.run(AurManager().list_installed()) == ["foo-bin", "bar-git"]


def test_search_parses_two_line_results(paru, scripted_exec):
    scripted_exec.add("paru -Ssa tool", stdout=(
        "aur/mytool 2.1-1 (+12 0.50)\n    A handy tool\n"
        "aur/mytool-git r5-1 (+3 0.01)\n    Git version\n"
    ))
    results = asyncio.run(AurManager().search_packages("tool"))
    assert results[0] == {"name": "mytool", "id": "mytool", "description": "A handy tool", "version": "2.1-1"}
    assert [r["name"] for r in results] == ["mytool", "mytool-git"]


def test_search_no_match_exit_1_is_empty(paru, scripted_exec):
    scripted_exec.add("paru -Ssa", rc=1)
    assert asyncio.run(AurManager().search_packages("zzz")) == []


def test_commands_never_use_pkexec(paru):
    mgr = AurManager()
    assert mgr.get_upgrade_command() == ["paru", "-Sua", "--noconfirm"]
    assert mgr.get_upgrade_command(["a", "b"]) == ["paru", "-S", "--noconfirm", "a", "b"]
    assert "pkexec" not in mgr.get_install_command("x")
