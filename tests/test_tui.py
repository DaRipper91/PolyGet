import asyncio
from unittest.mock import patch, AsyncMock

from app.ui.tui import PolyGetTuiApp


def test_send_phone_notification_kdeconnect_not_found():
    """kdeconnect-cli not installed: method returns early, no error logged."""
    app = PolyGetTuiApp()

    async def run_test():
        with patch("shutil.which", return_value=None):
            logged = []
            with patch("app.ui.tui._log", side_effect=lambda msg: logged.append(msg)):
                await app._send_phone_notification("test message")
        assert logged == []

    asyncio.run(run_test())


def test_send_phone_notification_failure_logged():
    """kdeconnect-cli calls fail: error is logged, method doesn't crash."""
    app = PolyGetTuiApp()

    async def run_test():
        with patch("shutil.which", return_value="/usr/bin/kdeconnect-cli"):
            async def failing_communicate():
                raise OSError("device unreachable")
            mock_proc = AsyncMock()
            mock_proc.returncode = 1
            mock_proc.communicate = failing_communicate
            with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
                logged = []
                with patch("app.ui.tui._log", side_effect=lambda msg: logged.append(msg)):
                    await app._send_phone_notification("test message")
        assert any("phone notification failed" in msg for msg in logged)

    asyncio.run(run_test())


def test_send_phone_notification_success():
    """kdeconnect-cli calls succeed: no error logged."""
    app = PolyGetTuiApp()

    async def run_test():
        with patch("shutil.which", return_value="/usr/bin/kdeconnect-cli"):
            async def success_communicate():
                return (b"device-id-123\n", b"")
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = success_communicate
            with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
                logged = []
                with patch("app.ui.tui._log", side_effect=lambda msg: logged.append(msg)):
                    await app._send_phone_notification("test message")
        assert logged == []

    asyncio.run(run_test())
