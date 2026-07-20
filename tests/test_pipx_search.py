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

def test_pipx_index_cache_write_is_atomic_and_serializes_concurrent_downloads(tmp_path):
    """Two concurrent search calls racing past the staleness check must not corrupt
    the cache file, and the shared lock should mean only one of them actually
    downloads while the other re-checks the now-fresh cache (audit finding B6)."""
    manager = PipxManager()
    cache_path = tmp_path / "pypi_simple_index.json"

    call_count = 0

    async def fake_create_subprocess_exec(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        proc = AsyncMock()
        proc.communicate.return_value = (
            json.dumps({"projects": [{"name": "black"}, {"name": "requests"}]}).encode(),
            b""
        )
        return proc

    with patch.object(PipxManager, "_INDEX_CACHE_PATH", cache_path):
        async def run_test():
            with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess_exec):
                results = await asyncio.gather(
                    manager._ensure_index_cached(),
                    manager._ensure_index_cached(),
                )

            assert results[0] == ["black", "requests"]
            assert results[1] == ["black", "requests"]
            assert call_count == 1

            # The cache file itself must be valid, complete JSON — no truncation/interleaving.
            assert json.loads(cache_path.read_text(encoding="utf-8")) == ["black", "requests"]
            # No leftover temp files from the atomic write-then-rename.
            assert list(tmp_path.glob(".pypi_simple_index_*.tmp")) == []

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
