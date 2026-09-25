import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from app.core.manager import PackageManager
from app.ui.tui import PolyGetTuiApp, _looks_like_pkexec_no_agent_failure, _looks_like_sudo_auth_failure


@pytest.fixture(autouse=True)
def fake_keyring(monkeypatch):
    """In-memory stand-in for the OS keyring so tests never touch the real one."""
    store: dict[str, str] = {}
    monkeypatch.setattr("app.core.sudo_secret.available", lambda: True)
    monkeypatch.setattr("app.core.sudo_secret.load", lambda: store.get("pw"))
    monkeypatch.setattr("app.core.sudo_secret.save", lambda pw: store.__setitem__("pw", pw) or True)
    monkeypatch.setattr("app.core.sudo_secret.forget", lambda: store.pop("pw", None) is not None)
    return store


def _proc(returncode: int, stderr: bytes = b"", pid: int = 1111) -> AsyncMock:
    proc = AsyncMock()
    proc.returncode = returncode
    proc.pid = pid
    proc.stdout.readline.side_effect = [b""]
    proc.stderr.readline.side_effect = ([stderr] if stderr else []) + [b""]
    proc.wait.return_value = returncode
    return proc


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
                        callback(("typed-password", False))

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


def _run_sudo_upgrade(procs, modal_answer):
    """Drive one sudo upgrade through the TUI; returns (result, argv list, modal count)."""
    async def run_test():
        with patch("app.ui.tui.discover_managers", return_value=[]), \
             patch("app.ui.tui.shutil.which", return_value=None):
            app = PolyGetTuiApp()
            async with app.run_test():
                mgr = MagicMock(spec=PackageManager)
                mgr.name = "DNF"
                mgr.get_upgrade_command.return_value = ["sudo", "dnf", "upgrade", "-y"]
                created, modals = [], []

                async def fake_exec(*args, **kwargs):
                    created.append(args)
                    return procs[len(created) - 1]

                def fake_push_screen(screen, callback=None):
                    modals.append(screen)
                    callback(modal_answer)

                with patch("asyncio.create_subprocess_exec", side_effect=fake_exec), \
                     patch.object(app, "push_screen", side_effect=fake_push_screen):
                    return await app._upgrade_manager(mgr), created, len(modals)

    return asyncio.run(run_test())


def test_looks_like_sudo_auth_failure():
    assert _looks_like_sudo_auth_failure("sudo: 1 incorrect password attempt") is True
    assert _looks_like_sudo_auth_failure("sudo: no password was provided") is True
    assert _looks_like_sudo_auth_failure("Error: Failed to download metadata") is False


def test_saved_keyring_password_is_used_without_prompting(fake_keyring):
    fake_keyring["pw"] = "saved-pw"
    ok = _proc(0)
    result, created, modal_count = _run_sudo_upgrade([ok], modal_answer=None)
    assert result is True and modal_count == 0 and len(created) == 1
    ok.stdin.write.assert_called_once_with(b"saved-pw\n")


def test_rejected_saved_password_is_forgotten_then_typed_one_is_remembered(fake_keyring):
    fake_keyring["pw"] = "old-pw"
    rejected = _proc(1, b"sudo: 1 incorrect password attempt\n")
    ok = _proc(0, pid=2222)
    result, created, modal_count = _run_sudo_upgrade([rejected, ok], modal_answer=("new-pw", True))
    assert result is True and modal_count == 1
    ok.stdin.write.assert_called_once_with(b"new-pw\n")
    assert fake_keyring["pw"] == "new-pw"


def test_saved_password_kept_when_command_itself_fails(fake_keyring):
    fake_keyring["pw"] = "good-pw"
    failed = _proc(1, b"Error: Failed to download metadata\n")
    result, _, modal_count = _run_sudo_upgrade([failed], modal_answer=None)
    assert result is False and modal_count == 0
    assert fake_keyring["pw"] == "good-pw"


def test_typed_password_not_saved_when_remember_unchecked(fake_keyring):
    ok = _proc(0, pid=2222)
    result, _, _ = _run_sudo_upgrade([_proc(1, b"sudo: no password was provided\n"), ok],
                                     modal_answer=("typed", False))
    assert result is True and "pw" not in fake_keyring
