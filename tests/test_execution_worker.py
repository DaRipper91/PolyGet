"""Tests for ExecutionWorker's pkexec → sudo fallback behavior."""

import sys
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from PySide6.QtWidgets import QApplication

from app.ui.main_window import ExecutionWorker


@pytest.fixture(scope="session")
def qapp():
    """Fixture to initialize QApplication for Qt tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def _proc(returncode: int, stdout: bytes = b"", stderr: bytes = b"", pid: int = 1111) -> AsyncMock:
    """Build a fake subprocess whose stdout/stderr are line-readable."""
    proc = AsyncMock()
    proc.returncode = returncode
    proc.pid = pid
    proc.stdout.readline.side_effect = [stdout + b"\n", b""] if stdout else [b""]
    proc.stderr.readline.side_effect = [stderr + b"\n", b""] if stderr else [b""]
    proc.wait.return_value = returncode
    return proc


def test_looks_like_pkexec_no_agent_failure_detects_known_markers(qapp):
    """Only recognized no-auth-agent markers trigger the fallback."""
    assert ExecutionWorker._looks_like_pkexec_no_agent_failure(
        "Error: No session for cookie"
    ) is True
    assert ExecutionWorker._looks_like_pkexec_no_agent_failure(
        "polkitd: authentication agent not found"
    ) is True
    assert ExecutionWorker._looks_like_pkexec_no_agent_failure(
        "Not Authorized to perform this action"
    ) is True
    assert ExecutionWorker._looks_like_pkexec_no_agent_failure(
        "cannot determine the session"
    ) is True
    # Real command failures are NOT no-agent errors.
    assert ExecutionWorker._looks_like_pkexec_no_agent_failure(
        "E: Unable to locate package foo"
    ) is False
    assert ExecutionWorker._looks_like_pkexec_no_agent_failure("") is False


def test_pkexec_success_no_fallback(qapp):
    """A pkexec command that exits 0 succeeds with no sudo fallback."""
    results = []
    worker = ExecutionWorker(["pkexec", "dnf", "upgrade", "-y"])
    worker.finished_signal.connect(lambda ok: results.append(ok))

    first = _proc(0, stdout=b"Upgraded: 1 package", stderr=b"")
    calls = []

    async def fake_exec(*args, **kwargs):
        calls.append(args)
        return first

    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        worker.run()

    assert results == [True]
    assert calls[0][0] == "pkexec"  # only pkexec was tried, no sudo fallback


def test_pkexec_no_agent_failure_falls_back_to_sudo(qapp):
    """pkexec failing with a no-auth-agent marker retries with sudo."""
    results = []
    worker = ExecutionWorker(["pkexec", "dnf", "upgrade", "-y"])
    worker.finished_signal.connect(lambda ok: results.append(ok))

    logs = []
    worker.log_signal.connect(lambda m: logs.append(m))

    first = _proc(1, stderr=b"Error: No session for cookie\n")
    second = _proc(0, stdout=b"Complete!\n", stderr=b"")

    created = []

    async def fake_exec(*args, **kwargs):
        created.append(args)
        return first if len(created) == 1 else second

    with patch("app.core.sudo_secret.load", return_value=None), \
         patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        worker.run()

    assert results == [True]  # sudo fallback succeeded
    assert created[0][0] == "pkexec"   # first attempt: pkexec
    assert created[1][0] == "sudo"     # second attempt: sudo
    assert "-S" in created[1]          # sudo -S reads password from stdin
    assert any("falling back to sudo" in m.lower() for m in logs)


def test_pkexec_real_failure_no_fallback(qapp):
    """A pkexec failure without a no-auth-agent marker does not fall back to sudo."""
    results = []
    worker = ExecutionWorker(["pkexec", "dnf", "upgrade", "-y"])
    worker.finished_signal.connect(lambda ok: results.append(ok))

    proc = _proc(1, stderr=b"E: Unable to locate package foo\n")

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        worker.run()

    assert results == [False]  # failed, no fallback


def test_pkexec_no_agent_falls_back_to_sudo_with_keyring_password(qapp):
    """When a saved sudo password exists in the keyring, it is loaded for sudo -S."""
    results = []
    worker = ExecutionWorker(["pkexec", "dnf", "upgrade", "-y"])
    worker.finished_signal.connect(lambda ok: results.append(ok))

    first = _proc(1, stderr=b"Error: No session for cookie\n")
    second = _proc(0, stdout=b"Done\n", stderr=b"")

    created = []

    async def fake_exec(*args, **kwargs):
        created.append(args)
        return first if len(created) == 1 else second

    with patch("app.core.sudo_secret.load", return_value="saved-pw"), \
         patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        worker.run()

    assert results == [True]
    assert created[0][0] == "pkexec"   # first attempt: pkexec
    assert created[1][0] == "sudo"     # second attempt: sudo
    assert "-S" in created[1]          # sudo -S reads password from stdin


def test_sudo_command_no_pkexec_unchanged(qapp):
    """A command that already uses sudo is run as-is, no pkexec logic."""
    results = []
    worker = ExecutionWorker(["sudo", "dnf", "upgrade", "-y"])
    worker.finished_signal.connect(lambda ok: results.append(ok))

    proc = _proc(0, stdout=b"Updated\n", stderr=b"")

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        worker.run()

    assert results == [True]
