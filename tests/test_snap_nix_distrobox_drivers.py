import asyncio
import json

import pytest

from app.core.drivers.distrobox import DistroboxManager
from app.core.drivers.nix import NixManager, _store_version
from app.core.drivers.snap import SnapManager
from app.core.manager import DriverError

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


def test_nix_store_version_extraction():
    assert _store_version("/nix/store/abc123-ripgrep-14.1.0") == "14.1.0"
    assert _store_version("/nix/store/abc123-hello-2.12.1") == "2.12.1"
    assert _store_version("/nix/store/abc123-nodejs") == ""


def test_nix_profile_list_handles_new_and_legacy_json(scripted_exec):
    new = {"elements": {"ripgrep": {"storePaths": ["/nix/store/h-ripgrep-14.1.0"]}}}
    scripted_exec.add("profile list --json", stdout=json.dumps(new))
    assert asyncio.run(NixManager().list_installed_versions()) == {"ripgrep": "14.1.0"}
    scripted_exec.rules.clear()
    legacy = {"elements": [{"storePaths": ["/nix/store/h-hello-2.12.1"]}]}
    scripted_exec.add("profile list --json", stdout=json.dumps(legacy))
    assert asyncio.run(NixManager().list_installed_versions()) == {"hello-2.12.1": "2.12.1"}


def test_nix_search_ids_are_installable_flake_refs(scripted_exec):
    scripted_exec.add("search nixpkgs hello", stdout=json.dumps({
        "legacyPackages.x86_64-linux.hello": {"pname": "hello", "version": "2.12.1", "description": "Greeter"},
    }))
    assert asyncio.run(NixManager().search_packages("hello")) == [
        {"name": "hello", "id": "nixpkgs#hello", "description": "Greeter", "version": "2.12.1"}
    ]


def test_nix_commands_enable_flakes_and_default_to_nixpkgs():
    mgr = NixManager()
    install = mgr.get_install_command("hello")
    assert install[-2:] == ["install", "nixpkgs#hello"] and "nix-command flakes" in install
    assert mgr.get_install_command("github:o/r#pkg")[-1] == "github:o/r#pkg"
    assert mgr.get_upgrade_command()[-1] == "--all"
    with pytest.raises(NotImplementedError):
        asyncio.run(mgr.check_updates())


def test_nix_invalid_json_is_driver_error(scripted_exec):
    scripted_exec.add("profile list", stdout="warning: not json")
    with pytest.raises(DriverError):
        asyncio.run(NixManager().list_installed_versions())


def test_distrobox_lists_containers_with_images(scripted_exec):
    scripted_exec.add("distrobox list", stdout=(
        "ID           | NAME   | STATUS       | IMAGE\n"
        "a1b2c3d4e5f6 | arch   | Up 2 hours   | docker.io/library/archlinux:latest\n"
        "f6e5d4c3b2a1 | ubuntu | Exited       | ubuntu:24.04\n"
    ))
    assert asyncio.run(DistroboxManager().list_installed_versions()) == {
        "arch": "docker.io/library/archlinux:latest", "ubuntu": "ubuntu:24.04",
    }


def test_distrobox_commands():
    mgr = DistroboxManager()
    assert mgr.get_upgrade_command() == ["distrobox", "upgrade", "--all"]
    assert mgr.get_upgrade_command(["arch"]) == ["distrobox", "upgrade", "arch"]
    assert mgr.get_install_command("docker.io/library/fedora:40") == [
        "distrobox", "create", "--yes", "--name", "fedora", "--image", "docker.io/library/fedora:40"
    ]
    with pytest.raises(NotImplementedError):
        asyncio.run(mgr.check_updates())
