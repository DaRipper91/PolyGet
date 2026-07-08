"""Unit tests for the SubprocessCoordinator class."""

import os
import signal
from unittest.mock import patch
from app.core.coordinator import SubprocessCoordinator


def test_coordinator_singleton():
    """Verify that SubprocessCoordinator behaves as a singleton."""
    c1 = SubprocessCoordinator()
    c2 = SubprocessCoordinator()
    assert c1 is c2


def test_coordinator_register_unregister():
    """Verify registration and unregistration of process IDs."""
    coordinator = SubprocessCoordinator()
    # Clean up state to isolate this test
    coordinator._pids.clear()

    assert not coordinator.active_pids

    coordinator.register(12345)
    assert 12345 in coordinator.active_pids

    coordinator.register(67890)
    assert 12345 in coordinator.active_pids
    assert 67890 in coordinator.active_pids

    coordinator.unregister(12345)
    assert 12345 not in coordinator.active_pids
    assert 67890 in coordinator.active_pids

    coordinator.unregister(67890)
    assert not coordinator.active_pids


def test_coordinator_terminate_all():
    """Verify terminate_all calls os.killpg and clears PIDs."""
    coordinator = SubprocessCoordinator()
    coordinator._pids.clear()

    coordinator.register(101)
    coordinator.register(102)

    with patch("os.killpg") as mock_killpg:
        coordinator.terminate_all()

        # Verify killpg was called for each PID
        assert mock_killpg.call_count == 2
        mock_killpg.assert_any_call(101, signal.SIGTERM)
        mock_killpg.assert_any_call(102, signal.SIGTERM)

        # Verify coordinator active pids are cleared
        assert not coordinator.active_pids


def test_coordinator_terminate_all_lookup_error():
    """Verify terminate_all handles ProcessLookupError gracefully."""
    coordinator = SubprocessCoordinator()
    coordinator._pids.clear()
    coordinator.register(201)

    with patch("os.killpg", side_effect=ProcessLookupError) as mock_killpg:
        # Should not raise exception
        coordinator.terminate_all()

        mock_killpg.assert_called_once_with(201, signal.SIGTERM)
        assert not coordinator.active_pids


def test_coordinator_terminate_all_permission_error():
    """Verify terminate_all falls back to os.kill if os.killpg raises PermissionError."""
    coordinator = SubprocessCoordinator()
    coordinator._pids.clear()
    coordinator.register(301)

    with patch("os.killpg", side_effect=PermissionError) as mock_killpg, \
         patch("os.kill") as mock_kill:
        coordinator.terminate_all()

        mock_killpg.assert_called_once_with(301, signal.SIGTERM)
        mock_kill.assert_called_once_with(301, signal.SIGTERM)
        assert not coordinator.active_pids
