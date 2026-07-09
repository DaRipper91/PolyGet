import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from app.core.drivers.poetry import PoetryManager

def test_poetry_list_installed():
    manager = PoetryManager()
    
    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b"poetry-plugin-export 1.3.0 Poetry plugin to export dependencies\n"
            b"poetry-plugin-shell 1.0.0 Run shells\n",
            b""
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            installed = await manager.list_installed()
            
        assert installed == ["poetry-plugin-export", "poetry-plugin-shell"]

    asyncio.run(run_test())
