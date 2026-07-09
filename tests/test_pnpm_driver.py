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
