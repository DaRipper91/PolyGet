import asyncio
from unittest.mock import patch

from app.core.drivers.aur import AurManager


def test_aur_search_packages_even_lines_all_pairs_processed():
    """Even number of lines: every header+description pair is processed."""
    manager = AurManager()

    async def run_test():
        out = (
            "aur/alpha 1.0 (5 3)\n"
            "Description of alpha\n"
            "aur/beta 2.0 (8 6)\n"
            "Description of beta\n"
        )
        with patch("app.core.drivers.aur.run_capture", return_value=out):
            results = await manager.search_packages("query")

        assert len(results) == 2
        assert results[0] == {"name": "alpha", "id": "alpha", "description": "Description of alpha", "version": "1.0"}
        assert results[1] == {"name": "beta", "id": "beta", "description": "Description of beta", "version": "2.0"}

    asyncio.run(run_test())


def test_aur_search_packages_odd_lines_last_not_crashed():
    """Odd number of lines: the trailing line is not dropped via IndexError;
    complete pairs are still processed."""
    manager = AurManager()

    async def run_test():
        out = (
            "aur/alpha 1.0 (5 3)\n"
            "Description of alpha\n"
            "aur/beta 2.0\n"
        )
        with patch("app.core.drivers.aur.run_capture", return_value=out):
            results = await manager.search_packages("query")

        # Only the complete pair (alpha + description) is processed;
        # the trailing "aur/beta 2.0" has no description line and is ignored.
        assert len(results) == 1
        assert results[0] == {"name": "alpha", "id": "alpha", "description": "Description of alpha", "version": "1.0"}

    asyncio.run(run_test())


def test_aur_search_packages_empty():
    """Empty output: no results, no crash."""
    manager = AurManager()

    async def run_test():
        with patch("app.core.drivers.aur.run_capture", return_value=""):
            results = await manager.search_packages("query")

        assert results == []

    asyncio.run(run_test())


def test_aur_search_packages_single_line():
    """Single line (no pair): no results, no crash."""
    manager = AurManager()

    async def run_test():
        out = "aur/alpha 1.0 (5 3)\n"
        with patch("app.core.drivers.aur.run_capture", return_value=out):
            results = await manager.search_packages("query")

        assert results == []

    asyncio.run(run_test())
