import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from app.core.drivers.dart_pub import DartPubManager

def test_dart_pub_list_installed():
    manager = DartPubManager()
    
    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b"sass 1.62.0\n"
            b"stagehand 3.0.1\n",
            b""
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            installed = await manager.list_installed()
            
        assert installed == ["sass", "stagehand"]

    asyncio.run(run_test())

def test_dart_pub_search_packages():
    manager = DartPubManager()
    
    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b'{"packages":[{"package":"sass"},{"package":"sass_builder"}]}\n',
            b""
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            results = await manager.search_packages("sass")
            
        assert len(results) == 2
        assert results[0] == {"name": "sass", "id": "sass", "description": "", "version": ""}
        assert results[1]["name"] == "sass_builder"

    asyncio.run(run_test())
