import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from app.core.drivers.pnpm import PnpmManager

def test_pnpm_check_updates():
    manager = PnpmManager()
    
    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b'{\n'
            b'  "typescript": {\n'
            b'    "current": "5.0.0",\n'
            b'    "latest": "5.1.0"\n'
            b'  }\n'
            b'}\n',
            b""
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            updates = await manager.check_updates()
            
        assert len(updates) == 1
        assert updates[0] == {"name": "typescript", "current": "5.0.0", "new": "5.1.0"}

    asyncio.run(run_test())

def test_pnpm_check_updates_timeout_raises_not_hangs():
    """A hung pnpm outdated subprocess must raise, not hang forever (audit finding B1)."""
    manager = PnpmManager()

    async def run_test():
        mock_proc = AsyncMock()
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
                with pytest.raises(RuntimeError):
                    await manager.check_updates()

    asyncio.run(run_test())


def test_pnpm_list_installed_timeout_returns_empty():
    """A hung pnpm list subprocess should fail open to [], not hang (audit finding B1)."""
    manager = PnpmManager()

    async def run_test():
        mock_proc = AsyncMock()
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
                result = await manager.list_installed()
                assert result == []

    asyncio.run(run_test())


def test_pnpm_list_installed():
    manager = PnpmManager()
    
    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b'[\n'
            b'  {\n'
            b'    "dependencies": {\n'
            b'      "typescript": {},\n'
            b'      "eslint": {}\n'
            b'    }\n'
            b'  }\n'
            b']\n',
            b""
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            installed = await manager.list_installed()
            
        assert installed == ["typescript", "eslint"]

    asyncio.run(run_test())
