import asyncio
from unittest.mock import AsyncMock, patch
import pytest

from app.core.manager import discover_managers
from app.core.drivers.dnf import DnfManager
from app.core.drivers.flatpak import FlatpakManager
from app.core.drivers.pipx import PipxManager
from app.core.drivers.npm import NpmManager
from app.core.drivers.cargo import CargoManager


def test_dnf_list_installed_and_install_cmd():
    """Test DnfManager's list_installed parsing and get_install_command."""
    manager = DnfManager()
    assert manager.get_install_command("htop") == ["pkexec", "dnf", "install", "-y", "htop"]

    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b"Installed packages\n"
            b"7zip.aarch64                                           26.02-1.fc44                        updates\n"
            b"Box2D.aarch64                                          2.4.2-7.fc44                        fedora\n",
            b""
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            installed = await manager.list_installed()
        assert installed == ["7zip", "Box2D"]

    asyncio.run(run_test())


def test_flatpak_list_installed_and_install_cmd():
    """Test FlatpakManager's list_installed parsing and get_install_command."""
    manager = FlatpakManager()
    assert manager.get_install_command("org.gimp.GIMP") == ["flatpak", "install", "-y", "org.gimp.GIMP"]

    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b'[\n'
            b'  {"application_id": "org.gimp.GIMP", "version": "2.10.30"},\n'
            b'  {"application_id": "org.mozilla.firefox", "version": "100.0"}\n'
            b']',
            b""
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            installed = await manager.list_installed()
        assert installed == ["org.gimp.GIMP", "org.mozilla.firefox"]

    asyncio.run(run_test())


def test_pipx_list_installed_and_install_cmd():
    """Test PipxManager's list_installed parsing and get_install_command."""
    manager = PipxManager()
    assert manager.get_install_command("black") == ["pipx", "install", "black"]

    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b"black 22.3.0\n"
            b"mypy 0.950\n",
            b""
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            installed = await manager.list_installed()
        assert installed == ["black", "mypy"]

    asyncio.run(run_test())


def test_npm_list_installed_and_install_cmd():
    """Test NpmManager's list_installed parsing and get_install_command."""
    manager = NpmManager()
    assert manager.get_install_command("typescript") == ["npm", "install", "-g", "typescript"]

    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b'{\n'
            b'  "name": "lib",\n'
            b'  "dependencies": {\n'
            b'    "typescript": {"version": "4.6.3"},\n'
            b'    "pm2": {"version": "5.2.0"}\n'
            b'  }\n'
            b'}',
            b""
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            installed = await manager.list_installed()
        assert installed == ["typescript", "pm2"]

    asyncio.run(run_test())


def test_cargo_list_installed_and_install_cmd():
    """Test CargoManager's list_installed parsing and get_install_command."""
    manager = CargoManager()
    assert manager.get_install_command("ripgrep") == ["cargo", "install", "ripgrep"]

    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b"Package       Installed  Latest   Needs update\n"
            b"cargo-update  v20.0.3    v20.0.3  No\n"
            b"godam         v0.1.2     v0.1.2   No\n",
            b""
        )
        with patch("shutil.which", return_value="/usr/bin/cargo-install-update"), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            installed = await manager.list_installed()
        assert installed == ["cargo-update", "godam"]

    asyncio.run(run_test())


def test_flatpak_check_updates():
    """Test FlatpakManager's check_updates parsing with column commit and alt-id matching."""
    manager = FlatpakManager()

    async def run_test():
        # Test Case 1: Update with different commits and no alt-id (normal update)
        mock_list_proc1 = AsyncMock()
        mock_list_proc1.returncode = 0
        mock_list_proc1.communicate.return_value = (
            b'[\n'
            b'  {\n'
            b'    "application_id" : "org.kde.kate",\n'
            b'    "version" : "26.04.3",\n'
            b'    "branch" : "stable",\n'
            b'    "active_commit" : "a164b7760356",\n'
            b'    "options" : "system"\n'
            b'  }\n'
            b']\n',
            b""
        )

        mock_update_proc1 = AsyncMock()
        mock_update_proc1.returncode = 0
        mock_update_proc1.communicate.return_value = (
            b'[\n'
            b'  {\n'
            b'    "application_id" : "org.kde.kate",\n'
            b'    "version" : "26.04.3",\n'
            b'    "branch" : "stable",\n'
            b'    "commit" : "11d746b2fee3"\n'
            b'  }\n'
            b']\n',
            b""
        )

        def mock_exec1(*args, **kwargs):
            if "list" in args:
                return mock_list_proc1
            return mock_update_proc1

        with patch("asyncio.create_subprocess_exec", side_effect=mock_exec1):
            updates = await manager.check_updates()
        assert len(updates) == 1
        assert updates[0]["name"] == "org.kde.kate"
        assert updates[0]["current"] == "26.04.3 (a164b776)"
        assert updates[0]["new"] == "26.04.3 (11d746b2)"

        # Test Case 2: Ghost update where alt-id matches the remote commit (should be filtered out)
        mock_list_proc2 = AsyncMock()
        mock_list_proc2.returncode = 0
        mock_list_proc2.communicate.return_value = (
            b'[\n'
            b'  {\n'
            b'    "application_id" : "org.kde.kate",\n'
            b'    "version" : "26.04.3",\n'
            b'    "branch" : "stable",\n'
            b'    "active_commit" : "5e34b0ce7f7b",\n'
            b'    "options" : "system,alt-id=a164b7760356,current"\n'
            b'  }\n'
            b']\n',
            b""
        )

        mock_update_proc2 = AsyncMock()
        mock_update_proc2.returncode = 0
        mock_update_proc2.communicate.return_value = (
            b'[\n'
            b'  {\n'
            b'    "application_id" : "org.kde.kate",\n'
            b'    "version" : "26.04.3",\n'
            b'    "branch" : "stable",\n'
            b'    "commit" : "a164b7760356"\n'
            b'  }\n'
            b']\n',
            b""
        )

        def mock_exec2(*args, **kwargs):
            if "list" in args:
                return mock_list_proc2
            return mock_update_proc2

        with patch("asyncio.create_subprocess_exec", side_effect=mock_exec2):
            updates = await manager.check_updates()
        # Should filter out the update because alt-id matches remote_commit
        assert len(updates) == 0

    asyncio.run(run_test())


def test_active_managers_sanity():
    """Test that all active/available managers return valid types for list_installed and get_install_command."""
    async def run_test():
        managers = discover_managers()
        for mgr in managers:
            # Verify list_installed returns a list of strings
            installed = await mgr.list_installed()
            assert isinstance(installed, list)
            for item in installed:
                assert isinstance(item, str)

            # Verify get_install_command returns a list of strings
            cmd = mgr.get_install_command("dummy-package")
            assert isinstance(cmd, list)
            assert len(cmd) > 0
            for part in cmd:
                assert isinstance(part, str)

    asyncio.run(run_test())
