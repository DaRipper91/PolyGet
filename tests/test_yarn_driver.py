import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from app.core.drivers.yarn import YarnManager

def test_yarn_check_updates():
    manager = YarnManager()
    
    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b'{"type":"info","data":"some info"}\n'
            b'{"type":"table","data":{"body":[["typescript","5.0.0","5.0.4","5.1.0","global"],["webpack","5.70.0","5.75.0","5.80.0","global"]]}}\n',
            b""
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            updates = await manager.check_updates()
            
        assert len(updates) == 2
        assert updates[0] == {"name": "typescript", "current": "5.0.0", "new": "5.1.0"}
        assert updates[1] == {"name": "webpack", "current": "5.70.0", "new": "5.80.0"}

    asyncio.run(run_test())

def test_yarn_check_updates_timeout_raises_not_hangs():
    """A hung yarn outdated subprocess must raise, not hang forever (audit finding B1)."""
    manager = YarnManager()

    async def run_test():
        mock_proc = AsyncMock()
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
                with pytest.raises(RuntimeError):
                    await manager.check_updates()

    asyncio.run(run_test())


def test_yarn_list_installed_timeout_returns_empty():
    """A hung yarn list subprocess should fail open to [], not hang (audit finding B1)."""
    manager = YarnManager()

    async def run_test():
        mock_proc = AsyncMock()
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
                result = await manager.list_installed()
                assert result == []

    asyncio.run(run_test())


def test_yarn_list_installed():
    manager = YarnManager()
    
    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b"info \"typescript@5.0.4\" has binaries\n"
            b"- typescript@5.0.4\n"
            b"- webpack@5.80.0\n",
            b""
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            installed = await manager.list_installed()
            
        assert installed == ["typescript", "webpack"]

    asyncio.run(run_test())
