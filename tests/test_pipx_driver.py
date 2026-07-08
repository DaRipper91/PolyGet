import asyncio
from unittest.mock import AsyncMock, patch
import pytest
from app.core.drivers.pipx import PipxManager


def test_pipx_driver_imports():
    """Validate that the PipxManager driver can be imported and instantiated."""
    manager = PipxManager()
    assert manager.name == "Pipx"
    assert manager.category == "Language/Dev"


def test_pipx_driver_availability_true():
    """Test availability when pipx binary is in PATH."""
    with patch("shutil.which", return_value="/usr/bin/pipx"):
        manager = PipxManager()
        assert manager.is_available() is True


def test_pipx_driver_availability_false():
    """Test availability when pipx binary is NOT in PATH."""
    with patch("shutil.which", return_value=None):
        manager = PipxManager()
        assert manager.is_available() is False


def test_pipx_get_upgrade_command():
    """Test upgrade command generation."""
    manager = PipxManager()
    assert manager.get_upgrade_command() == ["pipx", "upgrade-all"]
    assert manager.get_upgrade_command(["pkg1", "pkg2"]) == ["pipx", "upgrade", "pkg1", "pkg2"]


def test_pipx_check_updates():
    """Test check_updates parses packages and gathers updates in parallel."""
    async def run_test():
        manager = PipxManager()

        mock_pipx_list_proc = AsyncMock()
        mock_pipx_list_proc.communicate.return_value = (b"package1 1.0.0\npackage2 2.0.0\n", b"")

        mock_pip_proc1 = AsyncMock()
        mock_pip_proc1.communicate.return_value = (
            b'[{"name": "package1", "version": "1.0.0", "latest_version": "1.1.0"}]',
            b""
        )

        mock_pip_proc2 = AsyncMock()
        mock_pip_proc2.communicate.return_value = (
            b'[{"name": "package2", "version": "2.0.0", "latest_version": "2.2.0"}]',
            b""
        )

        def create_subprocess_exec_side_effect(*args, **kwargs):
            if args[0] == "pipx" and args[1] == "list":
                return mock_pipx_list_proc
            elif "package1" in args[0]:
                return mock_pip_proc1
            elif "package2" in args[0]:
                return mock_pip_proc2
            raise ValueError(f"Unexpected subprocess call: {args}")

        with patch("asyncio.create_subprocess_exec", side_effect=create_subprocess_exec_side_effect), \
             patch("os.path.exists", return_value=True):
            updates = await manager.check_updates()

        assert len(updates) == 2
        assert updates[0] == {"name": "package1", "current": "1.0.0", "new": "1.1.0"}
        assert updates[1] == {"name": "package2", "current": "2.0.0", "new": "2.2.0"}

    asyncio.run(run_test())
