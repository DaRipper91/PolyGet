"""Bun and Snap driver tests copied from CachyOS/stable-candidate dbd1fbc (its files also cover
Deno/Nix/Distrobox, which this beta does not have). Delete this file when the candidate lands here."""

import asyncio
import json

import pytest

from app.core.drivers.bun import BunManager
from app.core.drivers.snap import SnapManager
from app.core.manager import DriverError


@pytest.fixture
def bun_home(tmp_path, monkeypatch):
    monkeypatch.setenv("BUN_INSTALL", str(tmp_path))
    return tmp_path / "install" / "global"


def _write_global(root, deps):
    root.mkdir(parents=True)
    (root / "package.json").write_text(json.dumps({"dependencies": {n: "^1" for n in deps}}))
    for name, version in deps.items():
        pkg = root / "node_modules" / name
        pkg.mkdir(parents=True)
        (pkg / "package.json").write_text(json.dumps({"version": version}))


def test_bun_without_global_dir_reports_nothing_instead_of_falling_back_to_cwd(bun_home, scripted_exec):
    # `bun pm ls -g` would list the cwd's node_modules here; the driver must not shell out at all.
    assert asyncio.run(BunManager().list_installed_versions()) == {}
    assert scripted_exec.calls == []


def test_bun_reads_installed_versions_from_disk(bun_home):
    _write_global(bun_home, {"@scope/tool": "1.2.0", "left-pad": "1.3.0"})
    assert asyncio.run(BunManager().list_installed_versions()) == {"@scope/tool": "1.2.0", "left-pad": "1.3.0"}


def test_bun_check_updates_encodes_scoped_names(bun_home, scripted_exec):
    _write_global(bun_home, {"@scope/tool": "1.2.0", "left-pad": "1.3.0"})
    scripted_exec.add("registry.npmjs.org/@scope%2Ftool/latest", stdout='{"version": "1.3.0"}')
    scripted_exec.add("registry.npmjs.org/left-pad/latest", stdout='{"version": "1.3.0"}')
    assert asyncio.run(BunManager().check_updates()) == [{"name": "@scope/tool", "current": "1.2.0", "new": "1.3.0"}]


def test_bun_commands():
    mgr = BunManager()
    assert mgr.get_upgrade_command() == ["bun", "update", "-g"]
    assert mgr.get_upgrade_command(["a"]) == ["bun", "update", "-g", "a"]
    assert mgr.get_install_command("a") == ["bun", "add", "-g", "a"]

SNAP_LIST = (
    "Name    Version   Rev   Tracking       Publisher   Notes\n"
    "core22   20240111  1380  latest/stable  canonical✓  base\n"
    "firefox  128.0     4500  latest/stable  mozilla✓    -\n"
)
SNAP_REFRESH = (
    "Name     Version  Rev   Size   Publisher  Notes\n"
    "firefox  129.0    4600  290MB  mozilla✓   -\n"
)
SNAP_FIND = (
    "Name   Version  Publisher  Notes  Summary\n"
    "vlc    3.0.20   videolan✓  -      The ultimate media player\n"
    "vlc-x  1.0      someone    -\n"
)


def test_snap_installed_and_updates_use_installed_version_as_current(scripted_exec):
    scripted_exec.add("snap list", stdout=SNAP_LIST)
    scripted_exec.add("snap refresh --list", stdout=SNAP_REFRESH)
    mgr = SnapManager()
    assert asyncio.run(mgr.list_installed_versions()) == {"core22": "20240111", "firefox": "128.0"}
    assert asyncio.run(mgr.check_updates()) == [{"name": "firefox", "current": "128.0", "new": "129.0"}]


def test_snap_no_pending_refresh_is_empty(scripted_exec):
    scripted_exec.add("snap list", stdout=SNAP_LIST)
    scripted_exec.add("snap refresh --list", stdout="", stderr="All snaps up to date.")
    assert asyncio.run(SnapManager().check_updates()) == []


def test_snap_daemon_down_is_an_error_not_a_clean_system(scripted_exec):
    scripted_exec.add("snap list", rc=1, stderr="error: cannot communicate with server")
    with pytest.raises(DriverError):
        asyncio.run(SnapManager().check_updates())


def test_snap_search_handles_missing_summary(scripted_exec):
    scripted_exec.add("snap find vlc", stdout=SNAP_FIND)
    results = asyncio.run(SnapManager().search_packages("vlc"))
    assert results[0] == {"name": "vlc", "id": "vlc", "version": "3.0.20", "description": "The ultimate media player"}
    assert results[1]["description"] == ""


def test_snap_commands_escalate_with_pkexec():
    mgr = SnapManager()
    assert mgr.get_upgrade_command() == ["pkexec", "snap", "refresh"]
    assert mgr.get_upgrade_command(["firefox"]) == ["pkexec", "snap", "refresh", "firefox"]
    assert mgr.get_install_command("vlc") == ["pkexec", "snap", "install", "vlc"]
