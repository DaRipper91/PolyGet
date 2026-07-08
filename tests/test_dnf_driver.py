import asyncio
from unittest.mock import AsyncMock, patch
import pytest
from app.core.drivers.dnf import DnfManager


def test_dnf_driver_imports():
    """Validate that the DnfManager driver can be imported and instantiated."""
    manager = DnfManager()
    assert manager.name == "DNF"
    assert manager.category == "System"


def test_dnf_driver_availability_true():
    """Test availability when dnf binary is in PATH."""
    with patch("shutil.which", return_value="/usr/bin/dnf"):
        manager = DnfManager()
        assert manager.is_available() is True


def test_dnf_driver_availability_false():
    """Test availability when dnf binary is NOT in PATH."""
    with patch("shutil.which", return_value=None):
        manager = DnfManager()
        assert manager.is_available() is False


def test_dnf_get_upgrade_command():
    """Test upgrade command generation uses pkexec."""
    manager = DnfManager()
    assert manager.get_upgrade_command() == ["pkexec", "dnf", "upgrade", "-y"]
    assert manager.get_upgrade_command(["pkg1"]) == ["pkexec", "dnf", "upgrade", "-y", "pkg1"]


def test_dnf_get_sync_command():
    """Test sync command generation uses pkexec."""
    manager = DnfManager()
    assert manager.get_sync_command() == ["pkexec", "dnf", "makecache"]


def test_dnf_check_updates_json():
    """Test check_updates parses packages using dnf check-update --json."""
    async def run_test():
        manager = DnfManager()

        mock_json_proc = AsyncMock()
        mock_json_proc.returncode = 100
        mock_json_proc.communicate.return_value = (
            b'{"upgrades": [{"name": "package1", "evr": "1.1.0"}]}',
            b""
        )

        with patch("asyncio.create_subprocess_exec", return_value=mock_json_proc) as mock_exec:
            updates = await manager.check_updates()
            mock_exec.assert_called_once_with(
                "dnf", "check-update", "--json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

        assert len(updates) == 1
        assert updates[0] == {"name": "package1", "current": "Installed", "new": "1.1.0"}

    asyncio.run(run_test())


def test_dnf_check_updates_fallback():
    """Test check_updates falls back to standard dnf check-update quiet output."""
    async def run_test():
        manager = DnfManager()

        mock_json_proc = AsyncMock()
        mock_json_proc.returncode = 1
        mock_json_proc.communicate.return_value = (b"", b"error or unsupported option")

        mock_fallback_proc = AsyncMock()
        mock_fallback_proc.returncode = 100
        mock_fallback_proc.communicate.return_value = (
            b"Last metadata expiration check: 0:05:00 ago.\n"
            b"package1.x86_64                     1.1.0-1.fc40                    updates\n",
            b""
        )

        def create_subprocess_exec_side_effect(*args, **kwargs):
            if "--json" in args:
                return mock_json_proc
            elif "--quiet" in args:
                return mock_fallback_proc
            raise ValueError(f"Unexpected subprocess call: {args}")

        with patch("asyncio.create_subprocess_exec", side_effect=create_subprocess_exec_side_effect) as mock_exec:
            updates = await manager.check_updates()
            assert mock_exec.call_count == 2

        assert len(updates) == 1
        assert updates[0] == {"name": "package1", "current": "Installed", "new": "1.1.0-1.fc40"}

    asyncio.run(run_test())
