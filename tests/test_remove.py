"""Uninstall support: driver remove commands, removal dry-runs, and `polyget remove`."""

import asyncio
import json

import pytest

import app.cli as cli
import app.core.settings_store as settings_store
from app.core.drivers.apt import AptManager
from app.core.drivers.dnf import DnfManager
from app.core.drivers.pacman import PacmanManager
from app.core.drivers.pipx import PipxManager
from app.core.manager import DriverError, PackageManager, get_all_managers


# --- Driver commands ---------------------------------------------------------------------------

def test_every_driver_with_install_can_remove_or_says_why_not():
    """A driver that can install should normally remove; the exceptions are deliberate."""
    unsupported = set()
    for mgr in get_all_managers():
        try:
            cmd = mgr.get_remove_command(["pkg"])
        except NotImplementedError:
            unsupported.add(mgr.name)
            continue
        # cmd[0] may be None here: helper-resolved binaries (paru/yay, conda, brew) aren't installed.
        assert isinstance(cmd, list) and all(isinstance(a, str) for a in cmd[1:]), mgr.name
        assert "pkg" in cmd, mgr.name
    # Go installs loose binaries; Bundler and Gradle are per-project, not global.
    assert unsupported == {"Go", "Bundler", "Gradle"}


def test_system_removals_escalate_with_pkexec():
    assert PacmanManager().get_remove_command(["a", "b"]) == ["pkexec", "pacman", "-Rs", "--noconfirm", "a", "b"]
    assert DnfManager().get_remove_command(["a"]) == ["pkexec", "dnf", "remove", "-y", "a"]
    assert AptManager().get_remove_command(["a"]) == ["pkexec", "apt-get", "remove", "-y", "a"]


def test_single_package_tools_flag_themselves():
    assert PipxManager.removes_one_at_a_time
    assert not PacmanManager.removes_one_at_a_time


# --- Dry-run parsers ---------------------------------------------------------------------------

def test_pacman_preview_lists_names(monkeypatch):
    seen = {}

    async def fake_capture(argv, **k):
        seen["argv"] = argv
        return "ripgrep\npcre2\n"

    monkeypatch.setattr("app.core.drivers.pacman.run_capture", fake_capture)
    assert asyncio.run(PacmanManager().preview_remove(["ripgrep"])) == ["ripgrep", "pcre2"]
    assert seen["argv"][:3] == ["pacman", "-Rs", "--print"] and "pkexec" not in seen["argv"]


def test_apt_simulated_removal_parse():
    out = (
        "Reading package lists...\n"
        "The following packages will be REMOVED:\n  ripgrep\n"
        "Remv ripgrep [13.0.0-4]\n"
        "Remv libfoo1 [1.2]\n"
    )
    assert AptManager._parse_simulated_removal(out) == ["ripgrep", "libfoo1"]


DNF4 = """\
Dependencies resolved.
================================================================================
 Package                 Architecture   Version             Repository     Size
================================================================================
Removing:
 ripgrep                 x86_64         13.0.0-6.fc39       @fedora       4.0 M
Removing unused dependencies:
 a-really-long-package-name-that-wraps
                         noarch         1.0-1.fc39          @fedora        10 k

Transaction Summary
================================================================================
Remove  2 Packages
"""

DNF5 = """\
Package                    Arch    Version              Repository      Size
Removing:
 ripgrep                   aarch64 14.1.0-1.fc40        fedora       4.0 MiB
Removing unused dependencies:
 pcre2                     aarch64 10.42-2.fc40         fedora     600.0 KiB

Transaction Summary:
 Removing:           2 packages
Operation aborted by the user.
"""


@pytest.mark.parametrize("output,expected", [
    (DNF4, ["ripgrep", "a-really-long-package-name-that-wraps"]),
    (DNF5, ["ripgrep", "pcre2"]),
])
def test_dnf_transaction_parse(output, expected):
    assert DnfManager._parse_removal_transaction(output) == expected


def test_dnf_preview_with_nothing_to_remove_is_an_error(monkeypatch):
    async def fake_capture(argv, **k):
        return "No match for argument: nope\n"

    monkeypatch.setattr("app.core.drivers.dnf.run_capture", fake_capture)
    with pytest.raises(DriverError):
        asyncio.run(DnfManager().preview_remove(["nope"]))


# --- CLI ---------------------------------------------------------------------------------------

class FakeSystem(PackageManager):
    name = "FakeSys"
    category = "System"

    def __init__(self, preview=None, preview_error=None):
        self._preview = preview
        self._preview_error = preview_error

    def is_available(self):
        return True

    def get_remove_command(self, packages):
        return ["fakesys", "remove"] + packages

    async def preview_remove(self, packages):
        if self._preview_error:
            raise DriverError(self._preview_error)
        if self._preview is None:
            raise NotImplementedError
        return self._preview


class FakeSingle(FakeSystem):
    name = "FakeOne"
    removes_one_at_a_time = True

    def get_remove_command(self, packages):
        assert len(packages) == 1
        return ["fakeone", "uninstall", packages[0]]


class NoRemove(FakeSystem):
    name = "NoRemove"

    def get_remove_command(self, packages):
        raise NotImplementedError("NoRemove does not support removing packages")


@pytest.fixture
def pool(monkeypatch, tmp_path):
    managers = {
        "sys": FakeSystem(preview=["ripgrep", "pcre2"]),
        "one": FakeSingle(),
        "none": NoRemove(),
    }
    monkeypatch.setattr(cli, "discover_managers", lambda: list(managers.values()))
    monkeypatch.setattr(cli, "get_all_managers", lambda: list(managers.values()))
    monkeypatch.setattr(
        settings_store, "_settings_instance", settings_store.SettingsStore(tmp_path / "settings.json")
    )
    return managers


def run_json(capsys, *argv):
    code = cli.main(["--json", *argv])
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.err


def test_remove_plans_and_shows_dependencies(pool, capsys, monkeypatch):
    ran = []
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: ran.append(a))
    code, data, err = run_json(capsys, "remove", "-m", "fakesys", "ripgrep")
    assert code == cli.EXIT_OK and ran == []
    assert data["executed"] is False
    assert data["steps"][0]["command"] == ["fakesys", "remove", "ripgrep"]
    assert data["steps"][0]["would_remove"] == ["ripgrep", "pcre2"]
    assert "pcre2" in err


def test_remove_failed_preview_blocks_even_with_yes(pool, capsys, monkeypatch):
    pool["sys"]._preview_error = "removing ripgrep breaks dependency required by foo"
    ran = []
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: ran.append(a))
    code, data, err = run_json(capsys, "remove", "-m", "fakesys", "ripgrep", "--yes")
    assert code == cli.EXIT_FAILED and ran == []
    assert data["executed"] is False and "breaks dependency" in data["error"]


def test_remove_single_package_tool_gets_one_step_each(pool, capsys):
    code, data, _ = run_json(capsys, "remove", "-m", "fakeone", "a", "b")
    assert code == cli.EXIT_OK
    assert [s["command"] for s in data["steps"]] == [["fakeone", "uninstall", "a"], ["fakeone", "uninstall", "b"]]


def test_remove_with_yes_executes(pool, capsys, monkeypatch):
    class Done:
        returncode = 0

    calls = []
    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, **k: calls.append(cmd) or Done())
    code, data, _ = run_json(capsys, "remove", "-m", "fakesys", "ripgrep", "--yes")
    assert code == cli.EXIT_OK
    assert calls == [["fakesys", "remove", "ripgrep"]]
    assert data["steps"][0]["success"] is True


def test_remove_unsupported_manager_is_usage_error(pool, capsys):
    assert cli.main(["remove", "-m", "noremove", "x"]) == cli.EXIT_USAGE
