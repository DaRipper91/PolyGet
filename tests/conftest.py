"""Point HOME at a throwaway dir before any app module computes its ~/.config / ~/.local paths,
so the suite never reads or writes the real user's settings, ignore list, history, or Qt state."""

import atexit
import os
import shutil
import tempfile
from unittest.mock import AsyncMock, patch

import pytest

REAL_HOME = os.environ.get("HOME", "")
os.environ["HOME"] = tempfile.mkdtemp(prefix="polyget-test-home-")
# Live tests run real dnf here, which caches ~400 MB of repo metadata under ~/.cache per run.
atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ.pop("XDG_CONFIG_HOME", None)
os.environ.pop("XDG_DATA_HOME", None)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Never reach the user's desktop session: GUI tests would pop real notifications ("Pre-upgrade
# hook failed: false"). Notifier falls back to the (absent) tray; test_notifier brings its own bus.
os.environ["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/nonexistent/polyget-test-bus"


@pytest.fixture
def real_home(monkeypatch):
    """For live-system tests: subprocesses (cargo, npm, gem...) need the real ~ to find their state."""
    monkeypatch.setenv("HOME", REAL_HOME)


class ScriptedExec:
    """Stand-in for asyncio.create_subprocess_exec that answers by matching the joined argv.

    Rules are checked in the order added; an unmatched command raises FileNotFoundError,
    which is what a missing binary does, so tests fail loudly on unexpected calls.
    """

    def __init__(self) -> None:
        self.rules: list[tuple[str, bytes, int, bytes]] = []
        self.calls: list[tuple[list[str], dict]] = []

    def add(self, needle: str, stdout: bytes | str = b"", rc: int = 0, stderr: bytes | str = b"") -> None:
        enc = lambda v: v.encode() if isinstance(v, str) else v
        self.rules.append((needle, enc(stdout), rc, enc(stderr)))

    async def __call__(self, *argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        joined = " ".join(str(a) for a in argv)
        for needle, stdout, rc, stderr in self.rules:
            if needle in joined:
                proc = AsyncMock()
                proc.returncode = rc
                proc.communicate.return_value = (stdout, stderr)
                return proc
        raise FileNotFoundError(argv[0])


@pytest.fixture
def scripted_exec():
    script = ScriptedExec()
    with patch("asyncio.create_subprocess_exec", script):
        yield script


_windows = []  # every MainWindow built this session, kept alive so its threads can be joined


@pytest.fixture(autouse=True, scope="session")
def track_windows():
    """GUI tests drop their MainWindow without closing it, and a QThread destroyed mid-run
    aborts the whole process. Track windows from the start (module-scoped ones included)."""
    import sys
    main_window = sys.modules.get("app.ui.main_window")
    if main_window is None:
        yield
        return
    real_init = main_window.MainWindow.__init__

    def tracking_init(self, *args, **kwargs):
        _windows.append(self)
        real_init(self, *args, **kwargs)

    main_window.MainWindow.__init__ = tracking_init
    yield
    main_window.MainWindow.__init__ = real_init
    _join_window_workers()


@pytest.fixture(autouse=True)
def join_window_workers():
    yield
    _join_window_workers()


def _join_window_workers():
    """Join each window's workers the way closeEvent does."""
    from PySide6.QtCore import QThread
    for window in _windows:
        # Some tests swap in fake workers; only real threads need joining.
        window.active_workers = [w for w in window.active_workers if isinstance(w, QThread)]
        window._shutdown_workers()
