import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from app.core.manager import PackageManager
from app.ui.tui import PolyGetTuiApp, _looks_like_pkexec_no_agent_failure


def test_looks_like_pkexec_no_agent_failure_detects_known_markers():
    """Only recognized no-auth-agent markers should trigger the sudo fallback path,
    not just any nonzero pkexec exit (audit finding B4)."""
    assert _looks_like_pkexec_no_agent_failure("Error: No session for cookie") is True
    assert _looks_like_pkexec_no_agent_failure("polkitd: authentication agent not found") is True
    assert _looks_like_pkexec_no_agent_failure("Not Authorized to perform this action") is True
    assert _looks_like_pkexec_no_agent_failure("E: Unable to locate package foo") is False
    assert _looks_like_pkexec_no_agent_failure("") is False


def test_pkexec_no_agent_failure_falls_back_to_sudo_password_retry():
    """When pkexec fails specifically because no polkit authentication agent is bound
    to the session, the TUI must offer PasswordModal's sudo-with-typed-password retry
    instead of just reporting the upgrade as failed (audit finding B4 — this was
    previously dead code because no driver returns literal 'sudo' anymore)."""
    async def run_test():
        with patch("app.ui.tui.discover_managers", return_value=[]), \
             patch("app.ui.tui.shutil.which", return_value=None):
            app = PolyGetTuiApp()
            async with app.run_test():
                mgr = MagicMock(spec=PackageManager)
                mgr.name = "DNF"
                mgr.get_upgrade_command.return_value = ["pkexec", "dnf", "upgrade", "-y"]

                first_proc = AsyncMock()
                first_proc.returncode = 127
                first_proc.pid = 1111
                first_proc.stdout.readline.side_effect = [b""]
                first_proc.stderr.readline.side_effect = [b"Error: No session for cookie\n", b""]
                first_proc.wait.return_value = 127

                second_proc = AsyncMock()
                second_proc.returncode = 0
                second_proc.pid = 2222
                second_proc.stdout.readline.side_effect = [b""]
                second_proc.stderr.readline.side_effect = [b""]
                second_proc.wait.return_value = 0

                created = []

                async def fake_exec(*args, **kwargs):
                    created.append(args)
                    return first_proc if len(created) == 1 else second_proc

                def fake_push_screen(screen, callback=None):
                    if callback is not None:
                        callback("typed-password")

                with patch("asyncio.create_subprocess_exec", side_effect=fake_exec), \
                     patch.object(app, "push_screen", side_effect=fake_push_screen):
                    result = await app._upgrade_manager(mgr)

                assert result is True
                assert created[0][0] == "pkexec"
                assert created[1][0] == "sudo"
                second_proc.stdin.write.assert_called_once_with(b"typed-password\n")

    asyncio.run(run_test())


def test_pkexec_failure_without_no_agent_marker_does_not_prompt_for_password():
    """A real pkexec/command failure (not an auth-agent problem) must not be masked as
    'needs a password' — no PasswordModal should be shown (audit finding B4)."""
    async def run_test():
        with patch("app.ui.tui.discover_managers", return_value=[]), \
             patch("app.ui.tui.shutil.which", return_value=None):
            app = PolyGetTuiApp()
            async with app.run_test():
                mgr = MagicMock(spec=PackageManager)
                mgr.name = "DNF"
                mgr.get_upgrade_command.return_value = ["pkexec", "dnf", "upgrade", "-y"]

                proc = AsyncMock()
                proc.returncode = 1
                proc.pid = 1111
                proc.stdout.readline.side_effect = [b""]
                proc.stderr.readline.side_effect = [b"E: Unable to locate package foo\n", b""]
                proc.wait.return_value = 1

                push_screen_calls = []

                def fake_push_screen(screen, callback=None):
                    push_screen_calls.append(screen)
                    if callback is not None:
                        callback(None)

                with patch("asyncio.create_subprocess_exec", return_value=proc), \
                     patch.object(app, "push_screen", side_effect=fake_push_screen):
                    result = await app._upgrade_manager(mgr)

                assert result is False
                assert push_screen_calls == []

    asyncio.run(run_test())
