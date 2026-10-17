"""Point HOME at a throwaway dir before any app module computes its ~/.config / ~/.local paths,
so the suite never reads or writes the real user's settings, ignore list, history, or Qt state."""

import os
import tempfile

import pytest

REAL_HOME = os.environ.get("HOME", "")
os.environ["HOME"] = tempfile.mkdtemp(prefix="polyget-test-home-")
os.environ.pop("XDG_CONFIG_HOME", None)
os.environ.pop("XDG_DATA_HOME", None)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def real_home(monkeypatch):
    """For live-system tests: subprocesses (cargo, npm, gem...) need the real ~ to find their state."""
    monkeypatch.setenv("HOME", REAL_HOME)
