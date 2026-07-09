import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path
from app.core.drivers.pipx import PipxManager

def test_pipx_search_packages_cache_hit():
    manager = PipxManager()
    
    # Mock cache path file exists and read_text returns ["black", "requests"]
    mock_exists = MagicMock(return_value=True)
    mock_mtime = MagicMock(return_value=1000)
    mock_stat = MagicMock()
    mock_stat.return_value.st_mtime = 1000
    
    mock_read = MagicMock(return_value='["black", "requests"]')
    
    # Mock time.time to be close to mtime so it's a cache hit
    with patch.object(Path, "exists", mock_exists), \
         patch.object(Path, "stat", mock_stat), \
         patch.object(Path, "read_text", mock_read), \
         patch("time.time", return_value=1010):
        
        async def run_test():
            names = await manager._ensure_index_cached()
            assert names == ["black", "requests"]

        asyncio.run(run_test())

def test_pipx_search_packages_substring_matching():
    manager = PipxManager()
    
    # Mock cached index returning black and requests
    with patch.object(manager, "_ensure_index_cached", return_value=["black", "requests"]):
        # Mock details response for "black"
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b'{"info": {"name": "black", "summary": "The uncompromising code formatter.", "version": "22.3.0"}}\n',
            b""
        )
        
        async def run_test():
            with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
                results = await manager.search_packages("BLA")
                
            assert len(results) == 1
            assert results[0] == {
                "name": "black",
                "id": "black",
                "description": "The uncompromising code formatter.",
                "version": "22.3.0"
            }

        asyncio.run(run_test())
