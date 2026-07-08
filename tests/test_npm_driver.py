import asyncio
from unittest.mock import AsyncMock, patch
import pytest
import os
from app.core.drivers.npm import NpmManager


def test_npm_driver_imports():
    """Validate that the NpmManager driver can be imported and instantiated."""
    manager = NpmManager()
    assert manager.name == "NPM"
    assert manager.category == "Language/Dev"
    assert manager._global_prefix is None


def test_npm_driver_availability_true():
    """Test availability when npm binary is in PATH."""
    with patch("shutil.which", return_value="/usr/bin/npm"):
        manager = NpmManager()
        assert manager.is_available() is True


def test_npm_driver_availability_false():
    """Test availability when npm binary is NOT in PATH."""
    with patch("shutil.which", return_value=None):
        manager = NpmManager()
        assert manager.is_available() is False


def test_npm_check_updates():
    """Test that check_updates fetches and caches prefix, and parses updates."""
    async def run_test():
        manager = NpmManager()

        mock_prefix_proc = AsyncMock()
        mock_prefix_proc.returncode = 0
        mock_prefix_proc.communicate.return_value = (b"/usr/local\n", b"")

        mock_outdated_proc = AsyncMock()
        mock_outdated_proc.communicate.return_value = (
            b'{"package1": {"current": "1.0.0", "latest": "1.1.0"}}',
            b""
        )

        def create_subprocess_exec_side_effect(*args, **kwargs):
            if "config" in args:
                return mock_prefix_proc
            elif "outdated" in args:
                return mock_outdated_proc
            raise ValueError(f"Unexpected subprocess call: {args}")

        with patch("asyncio.create_subprocess_exec", side_effect=create_subprocess_exec_side_effect):
            updates = await manager.check_updates()

        assert manager._global_prefix == "/usr/local"
        assert len(updates) == 1
        assert updates[0] == {"name": "package1", "current": "1.0.0", "new": "1.1.0"}

    asyncio.run(run_test())


def test_npm_get_upgrade_command_cached_prefix_restricted():
    """Test upgrade command when cached prefix requires sudo."""
    manager = NpmManager()
    manager._global_prefix = "/usr/local"

    # Mock os.access to return False for /usr/local
    with patch("os.access", return_value=False):
        cmd = manager.get_upgrade_command()
        assert cmd == ["sudo", "npm", "update", "-g"]


def test_npm_get_upgrade_command_cached_prefix_writable():
    """Test upgrade command when cached prefix does not require sudo."""
    manager = NpmManager()
    manager._global_prefix = "/home/user/.npm-global"

    with patch("os.access", return_value=True):
        cmd = manager.get_upgrade_command(["some-package"])
        assert cmd == ["npm", "update", "-g", "some-package"]


def test_npm_get_upgrade_command_env_prefix_restricted():
    """Test upgrade command fallback to environment variable prefix."""
    manager = NpmManager()
    assert manager._global_prefix is None

    with patch.dict(os.environ, {"NPM_CONFIG_PREFIX": "/usr"}), \
         patch("os.access", return_value=False):
        cmd = manager.get_upgrade_command()
        assert cmd == ["sudo", "npm", "update", "-g"]


def test_npm_get_upgrade_command_fallback_paths():
    """Test upgrade command fallback to standard directory checks."""
    manager = NpmManager()
    assert manager._global_prefix is None

    # Mock no env variable
    with patch.dict(os.environ, {}, clear=True), \
         patch("os.path.exists", side_effect=lambda path: path == "/usr/local"), \
         patch("os.access", side_effect=lambda path, mode: path != "/usr/local" if path == "/usr/local" else True):
        cmd = manager.get_upgrade_command()
        assert cmd == ["sudo", "npm", "update", "-g"]
