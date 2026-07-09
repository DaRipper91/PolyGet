import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from app.core.drivers.gem import GemManager

def test_gem_check_updates():
    manager = GemManager()
    
    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b"bundler (2.3.10 < 2.4.0)\n"
            b"rails (7.0.2 < 7.0.3.pre)\n",
            b""
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            updates = await manager.check_updates()
            
        assert len(updates) == 2
        assert updates[0] == {"name": "bundler", "current": "2.3.10", "new": "2.4.0"}
        assert updates[1] == {"name": "rails", "current": "7.0.2", "new": "7.0.3.pre"}

    asyncio.run(run_test())

def test_gem_list_installed():
    manager = GemManager()
    
    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b"bundler (2.3.10, 2.2.0)\n"
            b"jekyll (4.2.1)\n",
            b""
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            installed = await manager.list_installed()
            
        assert installed == ["bundler", "jekyll"]

    asyncio.run(run_test())

def test_gem_search_packages():
    manager = GemManager()
    
    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b"rails (7.0.3, 7.0.2)\n"
            b"rails-html-sanitizer (1.4.3)\n",
            b""
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            results = await manager.search_packages("rails")
            
        assert len(results) == 2
        assert results[0] == {
            "name": "rails",
            "id": "rails",
            "description": "",
            "version": "7.0.3"
        }
        assert results[1]["name"] == "rails-html-sanitizer"
        assert results[1]["version"] == "1.4.3"

    asyncio.run(run_test())
