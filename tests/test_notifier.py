import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.ui.notifier import CRITICAL, gv_str, notify_argv

HERE = Path(__file__).resolve().parent


def test_strings_are_quoted_as_gvariant_literals():
    assert gv_str("plain") == "'plain'"
    assert gv_str("it's") == "'it\\'s'"
    assert gv_str("a\\b\nc") == "'a\\\\b\\nc'"
    # A body that looks like GVariant syntax still arrives as a string, not an array.
    assert gv_str("[1, 2]") == "'[1, 2]'"


def test_notify_argv_has_exact_dbus_types():
    argv = notify_argv(7, "Title", "Body", [("retry", "Retry")], CRITICAL, 140)
    assert argv[:9] == ["gdbus", "call", "--session", "--dest", "org.freedesktop.Notifications",
                        "--object-path", "/org/freedesktop/Notifications", "--method",
                        "org.freedesktop.Notifications.Notify"]
    assert argv[10] == "uint32 7"                     # replaces_id is a uint32
    assert argv[14] == "['retry', 'Retry']"
    assert "'urgency': <byte 2>" in argv[15] and "'value': <int32 100>" in argv[15]  # clamped
    assert argv[16] == "int32 -1"                     # not parsed as a command-line option
    assert notify_argv(0, "T", "B", [], 1, None)[14] == "@as []"


@pytest.mark.skipif(not (shutil.which("dbus-run-session") and shutil.which("gdbus")),
                    reason="needs dbus-run-session and gdbus")
def test_round_trip_on_a_private_session_bus():
    """Send, get an id back, receive a click, replace in place, and close — against a fake
    notification server on a throwaway bus (never the user's own session)."""
    py = sys.executable
    script = (f"'{py}' -I '{HERE / 'dbus' / 'fake_notification_server.py'}' 3200 & sleep 0.6; "
              f"'{py}' -I '{HERE / 'dbus' / 'notifier_client.py'}'; wait")
    out = subprocess.run(["dbus-run-session", "--", "bash", "-c", script],
                         capture_output=True, text=True, timeout=30).stdout
    assert "AVAILABLE True" in out
    assert "NOTIFY 41 0 6 updates ready | DNF 3 · it's\\nmajor ['update-all', 'Update all', 'open', 'Open']" in out
    assert "'urgency': 1" in out and "'desktop-entry': 'polyget'" in out
    assert "ACTION updates update-all" in out            # the click came back, mapped to its key
    assert "NOTIFY 41 41 7 updates ready" in out           # same key -> replaced id 41 in place
    assert "'value': 40" in out
    assert "CLOSE 41" in out
