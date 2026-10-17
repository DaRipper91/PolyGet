import asyncio
import subprocess
from unittest.mock import patch, AsyncMock

from app.core.drivers.pnpm import PnpmManager


def test_pnpm_needs_shell_fallback_direct_success():
    """Direct `pnpm --version` succeeds: no shell fallback needed."""
    manager = PnpmManager()

    with patch("shutil.which", return_value="/usr/bin/pnpm"):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            result = manager._needs_shell_fallback()
    assert result is False
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args[0] == "/usr/bin/pnpm"
    assert args[1] == "--version"


def test_pnpm_needs_shell_fallback_exec_format_error():
    """Direct `pnpm --version` raises OSError: shell fallback needed."""
    manager = PnpmManager()

    with patch("shutil.which", return_value="/usr/bin/pnpm"):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = OSError("[Errno 8] Exec format error")
            result = manager._needs_shell_fallback()
    assert result is True


def test_pnpm_needs_shell_fallback_subprocess_error():
    """`subprocess.run` raises SubprocessError: shell fallback needed."""
    manager = PnpmManager()

    with patch("shutil.which", return_value="/usr/bin/pnpm"):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.SubprocessError("failed")
            result = manager._needs_shell_fallback()
    assert result is True


def test_pnpm_needs_shell_fallback_cached():
    """Result is cached: subprocess.run called only once."""
    import subprocess

    manager = PnpmManager()

    with patch("shutil.which", return_value="/usr/bin/pnpm"):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            result1 = manager._needs_shell_fallback()
            result2 = manager._needs_shell_fallback()
    assert result1 is False
    assert result2 is False
    mock_run.assert_called_once()


def test_pnpm_pnpm_argv_no_fallback():
    """_pnpm_argv returns direct pnpm command when no fallback needed."""
    manager = PnpmManager()
    manager._shell_fallback = False
    result = manager._pnpm_argv("outdated", "--global", "--format", "json")
    assert result == ["pnpm", "outdated", "--global", "--format", "json"]


def test_pnpm_pnpm_argv_with_fallback():
    """_pnpm_argv returns sh-wrapped command when fallback needed."""
    manager = PnpmManager()
    manager._shell_fallback = True
    result = manager._pnpm_argv("outdated", "--global", "--format", "json")
    assert result == ["sh", "pnpm", "outdated", "--global", "--format", "json"]
