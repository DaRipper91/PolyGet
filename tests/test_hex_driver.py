import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from app.core.drivers.hex import HexManager

def test_hex_list_installed():
    manager = HexManager()
    
    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b"hex-2.0.0.ez *\n"
            b"phx_new-1.7.2.ez\n",
            b""
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            installed = await manager.list_installed()
            
        assert installed == ["hex", "phx_new"]

    asyncio.run(run_test())

def test_hex_search_packages():
    manager = HexManager()
    
    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b'[\n'
            b'  {\n'
            b'    "name": "phoenix",\n'
            b'    "meta": {"description": "Productive web framework"},\n'
            b'    "releases": [{"version": "1.7.2"}]\n'
            b'  }\n'
            b']\n',
            b""
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            results = await manager.search_packages("phoenix")
            
        assert len(results) == 1
        assert results[0] == {
            "name": "phoenix",
            "id": "phoenix",
            "description": "Productive web framework",
            "version": "1.7.2"
        }

    asyncio.run(run_test())
