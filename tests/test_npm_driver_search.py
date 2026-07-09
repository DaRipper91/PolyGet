import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from app.core.drivers.npm import NpmManager

def test_npm_search_packages():
    manager = NpmManager()

    async def run_test():
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b"[\n"
            b"  {\n"
            b"    \"name\": \"typescript\",\n"
            b"    \"version\": \"5.0.4\",\n"
            b"    \"description\": \"TypeScript is a language for application-scale JavaScript.\"\n"
            b"  }\n"
            b"]\n",
            b""
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            results = await manager.search_packages("typescript")
            
        assert len(results) == 1
        assert results[0] == {
            "name": "typescript",
            "id": "typescript",
            "description": "TypeScript is a language for application-scale JavaScript.",
            "version": "5.0.4"
        }

    asyncio.run(run_test())
