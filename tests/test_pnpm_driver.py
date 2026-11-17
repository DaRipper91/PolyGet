import asyncio
import subprocess
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from app.core.drivers.pnpm import PnpmManager
from app.core.manager import DriverError


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
    assert result == ["sh", manager._resolve(), "outdated", "--global", "--format", "json"]


def _proc(returncode=0, stdout=b"", stderr=b""):
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


def _check_updates(proc):
    manager = PnpmManager()
    manager._shell_fallback = False
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        return asyncio.run(manager.check_updates())


def test_pnpm_outdated_exit_1_with_json_reports_updates():
    out = b'{"is-odd": {"current": "2.0.0", "latest": "3.0.1"}}'
    assert _check_updates(_proc(1, out)) == [
        {"name": "is-odd", "current": "2.0.0", "new": "3.0.1"}
    ]


@pytest.mark.parametrize("out", [b"{}\n", b""])
def test_pnpm_successful_empty_outdated_query(out):
    assert _check_updates(_proc(0, out)) == []


def test_pnpm_no_global_manifest_means_nothing_installed():
    out = b'ERR_PNPM_NO_IMPORTER_MANIFEST_FOUND No package.json was found\n'
    assert _check_updates(_proc(1, out)) == []


@pytest.mark.parametrize("code,out,err", [
    (1, b"", b"ERR_PNPM_FETCH_404 registry request failed\n"),
    (2, b"{}", b"unexpected error"),
    (0, b"{not json", b""),
    (0, b"[]", b""),
])
def test_pnpm_failed_or_malformed_scan_raises_driver_error(code, out, err):
    with pytest.raises(DriverError, match=f"status {code}"):
        _check_updates(_proc(code, out, err))


@pytest.mark.parametrize("method,out,expected", [
    ("list_installed", b'[{"dependencies":{"tool":{"version":"1.2.3"}}}]', ["tool"]),
    ("list_installed_versions", b'[{"dependencies":{"tool":{"version":"1.2.3"}}}]', {"tool": "1.2.3"}),
    ("search_packages", b'[{"name":"tool","description":"utility","version":"1.2.3"}]',
     [{"name": "tool", "id": "tool", "description": "utility", "version": "1.2.3"}]),
])
def test_pnpm_other_queries_keep_working_with_stderr_capture(method, out, expected):
    manager = PnpmManager()
    manager._shell_fallback = False
    args = ("tool",) if method == "search_packages" else ()
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=_proc(0, out))):
        assert asyncio.run(getattr(manager, method)(*args)) == expected


def test_pnpm_shim_probe_runs_off_event_loop():
    manager = PnpmManager()
    seen = []

    async def fake_to_thread(fn, *args, **kwargs):
        seen.append(fn)
        return fn(*args, **kwargs)

    with patch("asyncio.to_thread", fake_to_thread), \
         patch("subprocess.run"), patch("shutil.which", return_value="/usr/bin/pnpm"), \
         patch("asyncio.create_subprocess_exec", AsyncMock(return_value=_proc(0, b"{}"))):
        asyncio.run(manager.check_updates())
    assert seen == [manager._needs_shell_fallback]
