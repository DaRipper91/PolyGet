import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path
from app.core.drivers.pipx import PipxManager
from app.core.manager import DriverError

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
        proc.returncode = 0
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


# ── A dead index must not read as "no packages matched" ───────────────────────
#
# `_ensure_index_cached` used to swallow every failure and return [], which the
# caller then reported as an honest empty result. The DriverError wrapper around
# search_packages could not catch it, because the failure happened one level
# deeper. These lock in the fixed behavior.


def _fresh_cache_path(tmp_path):
    return tmp_path / "pypi_simple_index.json"


def test_dead_index_raises_rather_than_returning_empty(tmp_path):
    """curl failing entirely must raise, not produce an empty search result."""
    manager = PipxManager()

    async def run_test():
        with patch.object(PipxManager, "_INDEX_CACHE_PATH", _fresh_cache_path(tmp_path)):
            with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError("curl")):
                with pytest.raises(DriverError, match="could not fetch the PyPI package index"):
                    await manager.search_packages("black")

    asyncio.run(run_test())


def test_index_curl_nonzero_exit_raises(tmp_path):
    """A non-fatal curl failure (e.g. HTTP 503) must raise, not look empty."""
    manager = PipxManager()

    async def run_test():
        async def fake_exec(*a, **k):
            proc = AsyncMock()
            proc.returncode = 22
            proc.communicate.return_value = (b"", b"curl: (22) HTTP error")
            return proc

        with patch.object(PipxManager, "_INDEX_CACHE_PATH", _fresh_cache_path(tmp_path)):
            with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
                with pytest.raises(DriverError, match="exited with status 22"):
                    await manager.search_packages("black")

    asyncio.run(run_test())


def test_index_html_error_page_raises(tmp_path):
    """A proxy/CDN HTML error page is malformed, not an empty index."""
    manager = PipxManager()

    async def run_test():
        async def fake_exec(*a, **k):
            proc = AsyncMock()
            proc.returncode = 0
            proc.communicate.return_value = (b"<html><body>502 Bad Gateway</body></html>", b"")
            return proc

        with patch.object(PipxManager, "_INDEX_CACHE_PATH", _fresh_cache_path(tmp_path)):
            with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
                with pytest.raises(DriverError, match="malformed PyPI package index"):
                    await manager.search_packages("black")

    asyncio.run(run_test())


def test_index_without_projects_key_raises(tmp_path):
    """Valid JSON that isn't the index we asked for must not become an empty result."""
    manager = PipxManager()

    async def run_test():
        async def fake_exec(*a, **k):
            proc = AsyncMock()
            proc.returncode = 0
            proc.communicate.return_value = (b'{"message": "rate limited"}', b"")
            return proc

        with patch.object(PipxManager, "_INDEX_CACHE_PATH", _fresh_cache_path(tmp_path)):
            with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
                with pytest.raises(DriverError, match="unusable PyPI package index"):
                    await manager.search_packages("black")

    asyncio.run(run_test())


def test_query_with_no_matches_is_a_true_empty(tmp_path):
    """The index loaded fine and simply had no match — that is a real answer."""
    manager = PipxManager()

    async def run_test():
        with patch.object(manager, "_ensure_index_cached", return_value=["black", "requests"]):
            assert await manager.search_packages("zzz-definitely-not-a-package") == []

    asyncio.run(run_test())


def test_all_detail_fetches_failing_raises(tmp_path):
    """Every matched package failing its detail fetch is a failed search, not
    'no packages matched' -- otherwise a PyPI outage looks like an empty result."""
    manager = PipxManager()

    async def run_test():
        with patch.object(manager, "_ensure_index_cached", return_value=["black", "black2"]):
            async def fake_detail(name):
                raise DriverError(f"could not fetch details for '{name}'")
            with patch.object(manager, "_fetch_package_detail", side_effect=fake_detail):
                with pytest.raises(DriverError, match="could not fetch details"):
                    await manager.search_packages("black")

    asyncio.run(run_test())


def test_partial_detail_failures_still_return_the_rest(tmp_path):
    """One unreachable package must not discard the other matches — search is
    best-effort per package, so the successful results survive."""
    manager = PipxManager()

    async def run_test():
        async def fake_detail(name):
            if name == "black2":
                raise DriverError("could not fetch details for 'black2'")
            return {"name": name, "id": name, "description": "ok", "version": "1.0.0"}

        with patch.object(manager, "_ensure_index_cached", return_value=["black", "black2"]):
            with patch.object(manager, "_fetch_package_detail", side_effect=fake_detail):
                results = await manager.search_packages("black")
                assert [r["name"] for r in results] == ["black"]

    asyncio.run(run_test())


def test_package_with_no_info_block_is_not_a_failure(tmp_path):
    """Listed in the index but carrying no `info` is a genuine None, not a broken fetch."""
    manager = PipxManager()

    async def run_test():
        async def fake_exec(*a, **k):
            proc = AsyncMock()
            proc.returncode = 0
            proc.communicate.return_value = (b'{"info": {}}', b"")
            return proc

        with patch.object(manager, "_ensure_index_cached", return_value=["black"]):
            with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
                assert await manager.search_packages("black") == []

    asyncio.run(run_test())


def test_poetry_inherits_the_pipx_index_failure():
    """Poetry delegates its search to pipx, so a dead PyPI index must surface for
    Poetry too rather than silently yielding nothing."""
    from app.core.drivers.poetry import PoetryManager

    manager = PoetryManager()

    async def run_test():
        async def fake_index(self):
            raise DriverError("Pipx could not fetch the PyPI package index")
        with patch("app.core.drivers.pipx.PipxManager._ensure_index_cached", fake_index):
            with pytest.raises(DriverError, match="PyPI package index"):
                await manager.search_packages("black")

    asyncio.run(run_test())
