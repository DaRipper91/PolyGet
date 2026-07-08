"""Subprocess lifecycle coordinator for tracking and terminating background process groups."""

import os
import signal
import threading
from typing import Set


class SubprocessCoordinator:
    """Thread-safe singleton class to track, register, unregister, and terminate

    active background child processes using process groups.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(SubprocessCoordinator, cls).__new__(cls, *args, **kwargs)
                    cls._instance._pids: Set[int] = set()
                    cls._instance._pid_lock = threading.Lock()
        return cls._instance

    def register(self, pid: int) -> None:
        """Register the process ID of a newly spawned background subprocess."""
        with self._pid_lock:
            self._pids.add(pid)

    def unregister(self, pid: int) -> None:
        """Unregister a process ID when the subprocess has terminated."""
        with self._pid_lock:
            self._pids.discard(pid)

    @property
    def active_pids(self) -> Set[int]:
        """Return a copy of the currently active registered process IDs."""
        with self._pid_lock:
            return set(self._pids)

    def terminate_all(self) -> None:
        """Terminate all active background child processes using process groups."""
        with self._pid_lock:
            pids_to_kill = list(self._pids)

        for pid in pids_to_kill:
            try:
                # Since preexec_fn=os.setsid is used, the spawned process has a process group ID
                # equal to its PID. We send SIGTERM to the entire process group.
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                # The process or process group does not exist (already exited).
                pass
            except PermissionError:
                # We may lack permission to kill this process group (e.g. if privileges dropped or escalated),
                # try killing the process directly as a fallback.
                try:
                    os.kill(pid, signal.SIGTERM)
                except Exception:
                    pass
            except Exception:
                pass

            # Cleanup regardless of whether kill succeeded
            with self._pid_lock:
                self._pids.discard(pid)
