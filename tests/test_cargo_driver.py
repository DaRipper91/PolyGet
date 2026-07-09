import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from app.core.drivers.cargo import CargoManager

def test_cargo_search_packages():
    manager = CargoManager()
    
    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b"tokio = \"1.28.0\"    # An event-driven, non-blocking I/O platform.\n"
            b"tokio-util = \"0.7.8\" # Utilities for working with Tokio.\n",
            b""
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            results = await manager.search_packages("tokio")
            
        assert len(results) == 2
        assert results[0] == {
            "name": "tokio",
            "id": "tokio",
            "description": "An event-driven, non-blocking I/O platform.",
            "version": "1.28.0"
        }
        assert results[1]["name"] == "tokio-util"

    asyncio.run(run_test())
