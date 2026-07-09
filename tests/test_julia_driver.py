import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from app.core.drivers.julia import JuliaManager

def test_julia_list_installed():
    manager = JuliaManager()
    
    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b"DataFrames\n"
            b"JSON\n"
            b"DataFrames\n", # test duplication filtering
            b""
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            installed = await manager.list_installed()
            
        assert installed == ["DataFrames", "JSON"]

    asyncio.run(run_test())
