import threading
from unittest.mock import patch

from app.core.coordinator import SubprocessCoordinator


def test_terminate_all_kills_each_registered_pid():
    """terminate_all() sends SIGTERM to every registered process group."""
    coord = SubprocessCoordinator()
    coord.register(1001)
    coord.register(1002)
    coord.register(1003)

    killed = []
    with patch("os.killpg", side_effect=lambda pid, sig: killed.append(pid)):
        coord.terminate_all()

    assert sorted(killed) == [1001, 1002, 1003]
    assert coord.active_pids == set()


def test_terminate_all_handles_process_lookup_error():
    """ProcessLookupError (already exited) is swallowed, pid still removed."""
    coord = SubprocessCoordinator()
    coord.register(2001)

    with patch("os.killpg", side_effect=ProcessLookupError):
        coord.terminate_all()

    assert coord.active_pids == set()


def test_terminate_all_blocks_concurrent_registration():
    """While terminate_all() holds the lock, concurrent register() calls block
    until terminate_all() releases the lock. No PID can be re-added mid-loop."""
    coord = SubprocessCoordinator()
    coord.register(4001)

    registration_done = threading.Event()
    registration_result = []

    def delayed_register():
        registration_done.wait()
        with coord._pid_lock:
            coord._pids.add(4002)
        registration_result.append("registered")

    # Start a thread that will try to register 4002, but block on the event.
    t = threading.Thread(target=delayed_register)
    t.start()

    # Run terminate_all() while 4002 registration is blocked.
    killed = []
    with patch("os.killpg", side_effect=lambda pid, sig: killed.append(pid)):
        coord.terminate_all()

    # Only 4001 was killed; 4002 wasn't registered yet when terminate_all ran.
    assert killed == [4001]
    assert coord.active_pids == set()

    # Now allow the registration to proceed; it should complete cleanly.
    registration_done.set()
    t.join()
    assert registration_result == ["registered"]

    # 4002 is now registered (not killed by the earlier terminate_all).
    assert coord.active_pids == {4002}
