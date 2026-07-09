import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from app.core.drivers.cpanm import CpanmManager

def test_cpanm_list_installed():
    manager = CpanmManager()
    
    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b"JSON\n"
            b"LWP::UserAgent\n",
            b""
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            installed = await manager.list_installed()
            
        assert installed == ["JSON", "LWP::UserAgent"]

    asyncio.run(run_test())

def test_cpanm_search_packages():
    manager = CpanmManager()
    
    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b'{"hits":{"hits":[{"_source":{"name":"JSON","version":"4.10"}}]}}\n',
            b""
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            results = await manager.search_packages("JSON")
            
        assert len(results) == 1
        assert results[0] == {
            "name": "JSON",
            "id": "JSON",
            "description": "",
            "version": "4.10"
        }

    asyncio.run(run_test())
